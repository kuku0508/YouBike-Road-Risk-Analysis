"""Synthetic-scale station cleaning executor with atomic partition publication."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from station_cleaning_contract import RepairContractError, apply_station_contract, load_allowlist

PIPELINE_VERSION = "station-cleaning-pipeline-v1"
ALLOWLIST_VERSION = "station-repair-policy-v2"
STATION_STATUSES = (
    "approved_repair", "candidate_only", "ambiguous", "unresolved",
    "unchanged_no_rule", "not_an_error",
)


class BatchContractError(RuntimeError):
    """The partition cannot be accepted safely."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _raw_from_record(record: dict[str, Any], side: str) -> tuple[str, str, bool]:
    key = f"{side}_station_raw_base64"
    try:
        raw_bytes = base64.b64decode(record[key], validate=True)
    except (KeyError, ValueError) as exc:
        raise BatchContractError(f"missing_or_invalid_{key}") from exc
    raw = raw_bytes.decode("utf-8", errors="surrogateescape")
    strict_utf8 = not any(0xDC80 <= ord(char) <= 0xDCFF for char in raw)
    display = raw if strict_utf8 else raw.encode("utf-8", "surrogateescape").decode("utf-8", "backslashreplace")
    return raw, display, strict_utf8


def load_station_universe(path: Path) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("classification") != "not_an_error" or not row.get("station_city"):
            raise BatchContractError("invalid_station_universe_fixture")
        rows[row["raw_value_base64"]] = row
    return rows


def _clean_side(record: dict[str, Any], side: str, rules: dict, universe: dict) -> dict[str, Any]:
    raw, raw_display, strict_utf8 = _raw_from_record(record, side)
    result = apply_station_contract(raw, rules)
    raw_key = record[f"{side}_station_raw_base64"]
    if result["repair_status"] == "unchanged_no_rule" and raw_key in universe:
        member = universe[raw_key]
        result.update(repair_status="not_an_error", station_city=member["station_city"])
    if not strict_utf8 and result["repair_status"] != "approved_repair":
        raise BatchContractError(f"serialization_unsafe_unapproved_{side}_station_raw")
    clean = result["station_clean"]
    try:
        clean.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise BatchContractError(f"serialization_unsafe_{side}_station_clean") from exc
    prefix = f"{side}_station_"
    return {
        prefix + "raw": raw_display,
        prefix + "raw_base64": raw_key,
        prefix + "clean": clean,
        prefix + "id": result["station_id"] or None,
        prefix + "city": result["station_city"] or None,
        prefix + "repair_status": result["repair_status"],
        prefix + "rule_version": result["rule_version"] or None,
        prefix + "evidence_tier": result["evidence_tier"] or None,
        prefix + "tier1_subtype": result["tier1_subtype"] or None,
    }


def clean_record(record: dict[str, Any], rules: dict, universe: dict) -> dict[str, Any]:
    required = {"borrow_time", "return_time", "duration_raw", "borrow_date", "bike_type",
                "_source_file", "_source_row", "_schema_version", "_parse_warnings"}
    missing = required.difference(record)
    if missing:
        raise BatchContractError("missing_parser_provenance_or_canonical_fields:" + ",".join(sorted(missing)))
    output = {key: record[key] for key in (
        "borrow_time", "return_time", "duration_raw", "bike_type", "borrow_date",
        "_source_file", "_source_row", "_schema_version")}
    # A canonical JSON string avoids schema drift when warning objects have
    # different keys, while preserving every parser-provided warning value.
    output["_parse_warnings"] = json.dumps(record["_parse_warnings"], ensure_ascii=False,
                                           sort_keys=True, separators=(",", ":"))
    output.update(_clean_side(record, "origin", rules, universe))
    output.update(_clean_side(record, "destination", rules, universe))
    # An empty station value is a parseable quality issue, not an execution
    # failure. The raw and Base64 fields must exist, but may represent b"".
    for side in ("origin", "destination"):
        if f"{side}_station_raw" not in output or f"{side}_station_raw_base64" not in output:
            raise BatchContractError("raw_station_invariant_failure")
    return output


def _write_parquet(records: list[dict[str, Any]], path: Path) -> None:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise BatchContractError("pyarrow_required_for_parquet") from exc
    try:
        table = pa.Table.from_pylist(records)
        pq.write_table(table, path, compression="zstd")
        # ParquetFile avoids dataset-style Hive partition columns being
        # synthesized from parent directories such as year=.../month=....
        roundtrip = pq.ParquetFile(path).read().to_pylist()
    except Exception as exc:
        raise BatchContractError("parquet_serialization_failure") from exc
    if roundtrip != records:
        raise BatchContractError("parquet_roundtrip_mismatch")


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_partition(input_path: Path, allowlist_path: Path, universe_path: Path,
                  output_root: Path, run_id: str, start_timestamp: str | None = None,
                  expected_allowlist_version: str = ALLOWLIST_VERSION) -> dict[str, Any]:
    """Stage, validate and atomically publish one partition; never publish partial output."""
    started = start_timestamp or datetime.now(timezone.utc).isoformat()
    final_dir = output_root / "year=synthetic" / "month=01"
    if final_dir.exists():
        raise BatchContractError("target_partition_already_exists")
    final_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=final_dir.parent))
    try:
        rules = load_allowlist(allowlist_path, expected_allowlist_version)
        universe = load_station_universe(universe_path)
        inputs = [json.loads(line) for line in input_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        cleaned: list[dict[str, Any]] = []
        quarantined: list[dict[str, Any]] = []
        for record in inputs:
            try:
                cleaned.append(clean_record(record, rules, universe))
            except (BatchContractError, RepairContractError) as exc:
                quarantined.append({
                    "raw_record": record,
                    "failure_reason": str(exc),
                    "source_provenance": {key: record.get(key) for key in
                                          ("_source_file", "_source_row", "_schema_version", "_parse_warnings")},
                    "pipeline_version": PIPELINE_VERSION,
                    "allowlist_version": expected_allowlist_version,
                    "timestamp": started,
                })
        if len(inputs) != len(cleaned) + len(quarantined):
            raise BatchContractError("record_conservation_failure")
        parquet_path = staging / "cleaned.parquet"
        quarantine_path = staging / "quarantine.jsonl"
        _write_parquet(cleaned, parquet_path)
        quarantine_path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                                           for row in quarantined), encoding="utf-8")
        counts = Counter()
        for row in cleaned:
            for side in ("origin", "destination"):
                counts[row[f"{side}_station_repair_status"]] += 1
        ended = started if start_timestamp else datetime.now(timezone.utc).isoformat()
        receipt = {
            "run_id": run_id,
            "pipeline_version": PIPELINE_VERSION,
            "allowlist_version": expected_allowlist_version,
            "allowlist_sha256": sha256_file(allowlist_path),
            "input_source_hashes": {input_path.name: sha256_file(input_path)},
            "input_record_count": len(inputs),
            "cleaned_record_count": len(cleaned),
            "quarantine_record_count": len(quarantined),
            **{f"{status}_count": counts[status] for status in STATION_STATUSES},
            "start_timestamp": started,
            "end_timestamp": ended,
            "output_hashes": {
                "cleaned.parquet": sha256_file(parquet_path),
                "quarantine.jsonl": sha256_file(quarantine_path),
            },
            "validation_status": "passed",
            "record_conservation": len(inputs) == len(cleaned) + len(quarantined),
        }
        _write_json(staging / "receipt.json", receipt)
        os.replace(staging, final_dir)
        return receipt
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--allowlist", type=Path, required=True)
    parser.add_argument("--station-universe", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--timestamp")
    args = parser.parse_args()
    print(json.dumps(run_partition(args.input, args.allowlist, args.station_universe,
                                   args.output_root, args.run_id, args.timestamp), indent=2))


if __name__ == "__main__":
    main()
