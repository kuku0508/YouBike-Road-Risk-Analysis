"""Run or safely resume the formal 2023/01--2025/03 monthly cleaning."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import time
from typing import Any

from clean_real_month import (ALLOWLIST_VERSION, FULL_PERIOD_MONTHS, PARSER_VERSION,
                              PIPELINE_VERSION, config_from_profile, run, sha256_file)
from clean_station_batch import STATION_STATUSES, BatchContractError

EXPECTED_TOTAL = 109_713_899


def profile_issue_count(scope: dict[str, Any], issue: str) -> int:
    """Read aggregate Phase 3 counts stored as {count, percentage} objects."""
    value = scope["issue_counts"].get(issue, 0)
    return value.get("count", 0) if isinstance(value, dict) else value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def validate_reusable(receipt_path: Path, partition: Path, raw_path: Path,
                      allowlist_path: Path, period: str) -> dict[str, Any] | None:
    internal = partition / "receipt.json"
    source = receipt_path if receipt_path.exists() else internal
    if not partition.exists() and not source.exists():
        return None
    if not partition.exists() or not source.exists():
        raise BatchContractError(f"incomplete existing state for {period}")
    receipt = json.loads(source.read_text(encoding="utf-8"))
    expected = {
        "period": period, "dry_run": False, "pipeline_version": PIPELINE_VERSION,
        "parser_version": PARSER_VERSION, "allowlist_version": ALLOWLIST_VERSION,
        "allowlist_sha256": sha256_file(allowlist_path), "validation_status": "passed",
    }
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise BatchContractError(f"existing receipt identity mismatch for {period}: {key}")
    if receipt["raw_source"]["sha256"] != sha256_file(raw_path):
        raise BatchContractError(f"existing source hash mismatch for {period}")
    outputs = {"cleaned.parquet": partition / "cleaned.parquet",
               "quarantine.jsonl": partition / "quarantine.jsonl"}
    for name, path in outputs.items():
        if not path.exists() or sha256_file(path) != receipt["output_hashes"][name]:
            raise BatchContractError(f"existing output hash mismatch for {period}: {name}")
    if not receipt_path.exists():
        _write_json(receipt_path, receipt)
    return receipt


def summarize(receipts: list[dict[str, Any]], profile_path: Path, started: float,
              run_id: str) -> dict[str, Any]:
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    baseline = profile["extended_report_period"]
    origin = Counter(); destination = Counter(); trips = Counter(); subtypes = Counter()
    bike = Counter(); quarantine_bike = Counter(); reasons = Counter()
    illegal = Counter(); repeated = Counter(); multiplicity = Counter()
    missing = Counter(); duration = Counter(); throughputs = []; output_bytes = Counter()
    monthly = []
    for receipt in receipts:
        for status in STATION_STATUSES:
            origin[status] += receipt["station_side_status_counts"]["origin"][status]
            destination[status] += receipt["station_side_status_counts"]["destination"][status]
        trips.update(receipt["trip_level_repair_counts"])
        subtypes.update(receipt["tier1_subtype_station_side_counts"])
        bike.update(receipt["bike_type_counts"]); quarantine_bike.update(receipt["quarantine_bike_type_counts"])
        reasons.update(receipt["quarantine_reason_counts"])
        enc = receipt["illegal_utf8"]
        for key in ("illegal_byte_count", "affected_field_count", "affected_record_count",
                    "origin_affected_records", "destination_affected_records",
                    "both_endpoints_affected_records", "approved_repair_accepted_station_sides",
                    "approved_repair_accepted_records", "unapproved_quarantine_records",
                    "unapproved_quarantine_station_sides"):
            illegal[key] += enc.get(key, 0)
        rep = receipt["repeated_identical_preservation"]
        for key in ("repeated_groups", "involved_records", "excess_copies"):
            repeated[key] += rep[key]
        multiplicity.update(rep["multiplicity_groups"])
        pre = receipt["preflight"]
        missing["origin_missing"] += pre["origin_missing"]
        missing["destination_missing"] += pre["destination_missing"]
        for key in ("duration_zero", "duration_gt_24h", "duration_gt_7d"):
            duration[key] += pre[key]
        throughputs.append(receipt["performance"]["rows_per_second"])
        output_bytes.update(receipt["output_bytes"])
        monthly.append({
            "month": receipt["period"], "input_records": receipt["input_records"],
            "accepted_records": receipt["accepted_records"], "quarantine_records": receipt["quarantine_records"],
            "source_sha256": receipt["raw_source"]["sha256"], "schema": pre["schema_version"],
            "allowlist_sha256": receipt["allowlist_sha256"], "pipeline_version": receipt["pipeline_version"],
            "cleaned_output_sha256": receipt["output_hashes"]["cleaned.parquet"],
            "quarantine_output_sha256": receipt["output_hashes"]["quarantine.jsonl"],
            "receipt_path": f"runs/full_cleaning/{run_id}/receipts/{receipt['period'].replace('/', '-')}.json",
            "validation_status": receipt["validation_status"],
            "wall_clock_seconds": receipt["performance"]["wall_clock_seconds"],
            "rows_per_second": receipt["performance"]["rows_per_second"],
            "peak_working_set_bytes": receipt["performance"]["peak_working_set_bytes"],
            "raw_bytes": receipt["raw_source"]["bytes"], **receipt["output_bytes"],
        })
    total_input = sum(r["input_records"] for r in receipts)
    total_accepted = sum(r["accepted_records"] for r in receipts)
    total_quarantine = sum(r["quarantine_records"] for r in receipts)
    cross_checks = {
        "month_count": len(receipts) == 27,
        "total_records": total_input == EXPECTED_TOTAL == baseline["total_records"],
        "record_conservation": total_input == total_accepted + total_quarantine,
        "monthly_records": all(item["input_records"] == baseline["monthly"][item["month"].replace("/", "-")]["total_records"]
                               for item in monthly),
        "illegal_byte_count": illegal["illegal_byte_count"] == baseline["encoding"]["illegal_byte_count"],
        "illegal_affected_fields": illegal["affected_field_count"] == baseline["encoding"]["affected_field_count"],
        "illegal_affected_records": illegal["affected_record_count"] == baseline["encoding"]["affected_record_count"],
        "bike_type_structural_null": bike["<NULL>"] == baseline["bike_type"]["v1_structural_absence"],
        "bike_type_normal": bike["一般車"] == baseline["bike_type"]["v2"]["一般車"],
        "bike_type_eassist": bike["電輔車"] == baseline["bike_type"]["v2"]["電輔車"],
        "repeated_groups": repeated["repeated_groups"] == baseline["repeated_identical"]["repeated_groups"],
        "repeated_involved_records": repeated["involved_records"] == baseline["repeated_identical"]["involved_records"],
        "repeated_excess_copies": repeated["excess_copies"] == baseline["repeated_identical"]["excess_copies"],
        "origin_missing": missing["origin_missing"] == profile_issue_count(baseline, "origin_missing"),
        "destination_missing": missing["destination_missing"] == profile_issue_count(baseline, "destination_missing"),
        "duration_zero": duration["duration_zero"] == profile_issue_count(baseline, "duration_zero"),
        "duration_gt_24h": duration["duration_gt_24h"] == profile_issue_count(baseline, "duration_gt_24h"),
        "duration_gt_7d": duration["duration_gt_7d"] == profile_issue_count(baseline, "duration_gt_7d"),
    }
    status = "complete" if all(cross_checks.values()) else "failed"
    return {
        "run_id": run_id, "scope": "2023/01-2025/03", "status": status,
        "pipeline_version": PIPELINE_VERSION, "parser_version": PARSER_VERSION,
        "allowlist_version": ALLOWLIST_VERSION, "month_count": len(receipts), "monthly": monthly,
        "global": {
            "total_input_records": total_input, "total_accepted_records": total_accepted,
            "total_quarantine_records": total_quarantine,
            "quarantine_rate": total_quarantine / total_input if total_input else None,
            "station_side_status_counts": {"origin": dict(origin), "destination": dict(destination),
                "combined": {status: origin[status] + destination[status] for status in STATION_STATUSES}},
            "trip_level_repair_counts": dict(trips),
            "at_least_one_repaired": total_accepted - trips["neither_side_repaired"],
            "tier1_subtype_station_side_counts": dict(subtypes),
            "illegal_utf8": dict(illegal), "bike_type_counts": dict(bike),
            "quarantine_bike_type_counts": dict(quarantine_bike),
            "quarantine_reason_counts": dict(reasons),
            "repeated_identical": {**dict(repeated), "multiplicity_groups": dict(multiplicity),
                                   "policy": "retain_all"},
            "missing_endpoints": dict(missing), "duration_validation": dict(duration),
        },
        "phase3a_cross_checks": cross_checks,
        "performance": {
            "orchestrator_wall_clock_seconds": time.perf_counter() - started,
            "sum_monthly_wall_clock_seconds": sum(r["performance"]["wall_clock_seconds"] for r in receipts),
            "monthly_throughput_min": min(throughputs), "monthly_throughput_median": statistics.median(throughputs),
            "monthly_throughput_max": max(throughputs),
            "peak_working_set_bytes_max": max(r["performance"]["peak_working_set_bytes"] or 0 for r in receipts),
            "output_bytes": dict(output_bytes),
        },
        "evidence_hashes": {
            "data_quality_profile": sha256_file(profile_path),
            "allowlist": receipts[0]["allowlist_sha256"],
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def execute(args) -> dict[str, Any]:
    started = time.perf_counter(); receipts = []
    progress_path = args.manifest.with_name(args.manifest.stem + "-progress.json")
    try:
        for index, period in enumerate(FULL_PERIOD_MONTHS, start=1):
            compact = period.replace("/", "-")
            config = config_from_profile(args.profile, period)
            raw = args.raw_dir / f"{config['month'].replace('-', '')}_YouBike2.0票證刷卡資料.zip"
            partition = args.output_root / f"year={config['year']}" / f"month={config['month_number']}"
            receipt_path = args.runs_root / args.run_id / "receipts" / f"{compact}.json"
            print(f"[{index:02d}/27] {period} CHECK", flush=True)
            receipt = validate_reusable(receipt_path, partition, raw, args.allowlist, period)
            if receipt is None:
                print(f"[{index:02d}/27] {period} RUN", flush=True)
                receipt = run(raw, args.allowlist, args.station_universe, args.profile,
                              args.output_root, receipt_path, f"{args.run_id}-{compact}", period,
                              args.schema_evidence, dry_run=False)
                print(f"[{index:02d}/27] {period} COMPLETE input={receipt['input_records']} "
                      f"accepted={receipt['accepted_records']} quarantine={receipt['quarantine_records']}", flush=True)
            else:
                print(f"[{index:02d}/27] {period} REUSED", flush=True)
            receipts.append(receipt)
            partial = {"run_id": args.run_id, "status": "in_progress", "completed_months": len(receipts),
                       "last_completed_month": period}
            _write_json(progress_path, partial)
    except Exception as exc:
        failure = {"run_id": args.run_id, "status": "failed", "completed_months": len(receipts),
                   "last_completed_month": receipts[-1]["period"] if receipts else None,
                   "failed_month": period, "error_type": type(exc).__name__, "error": str(exc),
                   "failed_at": datetime.now(timezone.utc).isoformat()}
        _write_json(progress_path, failure)
        raise
    manifest = summarize(receipts, args.profile, started, args.run_id)
    _write_json(args.manifest, manifest)
    if manifest["status"] != "complete":
        raise BatchContractError("full-period manifest cross-check failed: " +
            ",".join(key for key, ok in manifest["phase3a_cross_checks"].items() if not ok))
    progress_path.unlink(missing_ok=True)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, required=True); parser.add_argument("--allowlist", type=Path, required=True)
    parser.add_argument("--station-universe", type=Path, required=True); parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--schema-evidence", type=Path, required=True); parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--runs-root", type=Path, required=True); parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    print(json.dumps(execute(args), ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
