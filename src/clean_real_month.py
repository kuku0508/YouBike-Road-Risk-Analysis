"""Fail-closed, streaming real-month station-cleaning dry run."""
from __future__ import annotations

import argparse
import base64
from collections import Counter
import csv
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any
import zipfile
import re

from clean_station_batch import (ALLOWLIST_VERSION, PIPELINE_VERSION, STATION_STATUSES,
                                 BatchContractError, clean_record, sha256_file)
from station_cleaning_contract import RepairContractError, apply_station_contract, load_allowlist
from youbike_raw_parser import OBSERVED_BIKE_TYPES, iter_path

PERIOD = "2023/11"
EXPECTED_RECORDS = 2_941_065
EXPECTED_SCHEMA = "v1_6col"
EXPECTED_RAW_SHA256 = "97429096d6c6a7cd227ec1209c8559d1b71e573c50be75ecdef7c67fa28b2aca"
PARSER_VERSION = "youbike-raw-parser-contract-v1"
BATCH_SIZE = 50_000
MODULUS = 1 << 128
SUFFIX_RE = re.compile(r"_\d+\Z")
RUN_CONFIGS = {
    "2023/11": {"month": "2023-11", "year": "2023", "month_number": "11",
                "records": EXPECTED_RECORDS, "schema": EXPECTED_SCHEMA,
                "sha256": EXPECTED_RAW_SHA256, "bike_type": {"<NULL>": EXPECTED_RECORDS}},
    "2024/11": {"month": "2024-11", "year": "2024", "month_number": "11",
                "records": 5_883_102, "schema": "v2_7col",
                "sha256": "a255acf386d88fbb1429147b87c257017c4cff1f851b3860ded61ad3894bc20a",
                "bike_type": {"一般車": 5_733_169, "電輔車": 149_933}},
}
FULL_PERIOD_MONTHS = tuple(f"{year}/{month:02d}" for year in (2023, 2024) for month in range(1, 13)) + (
    "2025/01", "2025/02", "2025/03")


class SourceGateError(BatchContractError):
    pass


class MultisetFingerprint:
    """Order-independent dual fingerprint for exact raw-record preservation."""
    def __init__(self) -> None:
        self.count = 0
        self.total = 0
        self.xor = 0

    def add(self, record: dict[str, Any]) -> None:
        values = (record["borrow_time"], record["origin_station_raw"], record["return_time"],
                  record["destination_station_raw"], record["duration_raw"],
                  record["bike_type"], record["borrow_date"])
        framed = bytearray()
        for value in values:
            raw = b"<NULL>" if value is None else value.encode("utf-8", "surrogateescape")
            framed.extend(len(raw).to_bytes(4, "big")); framed.extend(raw)
        number = int.from_bytes(hashlib.sha256(framed).digest()[:16], "big")
        self.count += 1
        self.total = (self.total + number) % MODULUS
        self.xor ^= number

    def as_dict(self) -> dict[str, Any]:
        return {"count": self.count, "sum128": f"{self.total:032x}", "xor128": f"{self.xor:032x}"}


def combine_fingerprints(*fingerprints: dict[str, Any]) -> dict[str, Any]:
    xor_value = 0
    for item in fingerprints:
        xor_value ^= int(item["xor128"], 16)
    return {
        "count": sum(item["count"] for item in fingerprints),
        "sum128": f"{sum(int(item['sum128'], 16) for item in fingerprints) % MODULUS:032x}",
        "xor128": f"{xor_value:032x}",
    }


def raw_member(path: Path) -> tuple[str, int]:
    with zipfile.ZipFile(path) as archive:
        members = [item for item in archive.infolist() if not item.is_dir()]
        if len(members) != 1 or not members[0].filename.lower().endswith(".csv"):
            raise SourceGateError("ZIP must contain exactly one CSV member")
        return members[0].filename, members[0].file_size


def profile_expectations(profile_path: Path, month: str) -> dict[str, Any]:
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    scope = profile if month in profile["monthly"] else profile["extended_report_period"]
    monthly = scope["monthly"][month]
    file_info = next(row for row in scope["files"] if row["month"] == month)
    return {"monthly": monthly, "file": file_info}


def config_from_profile(profile_path: Path, period: str) -> dict[str, Any]:
    month = period.replace("/", "-")
    expected = profile_expectations(profile_path, month)
    file_info = expected["file"]
    schema = file_info["schema_version"]
    return {"month": month, "year": month[:4], "month_number": month[5:7],
            "records": file_info["records"], "schema": schema, "sha256": file_info["sha256"],
            "bike_type": {"<NULL>": file_info["records"]} if schema == "v1_6col" else None}


def expected_issue_count(monthly: dict[str, Any], issue: str) -> int:
    """Phase 3 omits zero-count issue keys from some monthly sparse maps."""
    return monthly["issue_counts"].get(issue, 0)


def schema_bike_baseline(path: Path, month: str) -> dict[str, int]:
    evidence = json.loads(path.read_text(encoding="utf-8"))
    row = next((item for item in evidence["months"] if item["month"] == month), None)
    return dict(row.get("sixth_field_top_values", [])) if row else {}


def preflight(raw_path: Path, profile_path: Path, config: dict[str, Any] | None = None,
              schema_evidence_path: Path | None = None) -> dict[str, Any]:
    config = config or RUN_CONFIGS[PERIOD]
    expected = profile_expectations(profile_path, config["month"])
    actual_hash = sha256_file(raw_path)
    member, member_bytes = raw_member(raw_path)
    if actual_hash != config["sha256"] or actual_hash != expected["file"]["sha256"]:
        raise SourceGateError("raw SHA-256 differs from Phase 2/3 evidence")
    if member != expected["file"]["csv_member"]:
        raise SourceGateError("CSV member differs from Phase 3 evidence")
    count = 0; origin_missing = 0; destination_missing = 0; warning_records = 0
    duration_zero = 0; duration_gt_24h = 0; duration_gt_7d = 0
    bike_types = Counter(); station_patterns = Counter(); illegal = Counter()
    illegal_values = {"origin": set(), "destination": set()}
    fingerprint = MultisetFingerprint()
    first_source_row = None; last_source_row = None
    for record in iter_path(raw_path):
        count += 1
        first_source_row = first_source_row or record["_source_row"]
        last_source_row = record["_source_row"]
        if record["_schema_version"] != config["schema"]:
            raise SourceGateError("schema differs from expected version")
        bike_types["<NULL>" if record["bike_type"] is None else record["bike_type"]] += 1
        warning_records += bool(record["_parse_warnings"])
        origin_missing += record["origin_station_raw"] == ""
        destination_missing += record["destination_station_raw"] == ""
        hours, minutes, seconds = map(int, record["duration_raw"].split(":"))
        duration = hours * 3600 + minutes * 60 + seconds
        duration_zero += duration == 0
        duration_gt_24h += duration > 86_400
        duration_gt_7d += duration > 604_800
        affected_sides = set()
        for warning in record["_parse_warnings"]:
            illegal["illegal_byte_count"] += warning["invalid_byte_count"]
            illegal["affected_field_count"] += 1
            side = "origin" if warning["field"] == "origin_station_raw" else "destination"
            affected_sides.add(side); illegal_values[side].add(warning["field_bytes_base64"])
        if affected_sides:
            illegal["affected_record_count"] += 1
            for side in affected_sides: illegal[f"{side}_affected_records"] += 1
            illegal["both_endpoints_affected_records"] += len(affected_sides) == 2
        for side in ("origin", "destination"):
            value = record[f"{side}_station_raw"]
            station_patterns[f"{side}_numeric_suffix"] += bool(SUFFIX_RE.search(value))
            station_patterns[f"{side}_question_mark"] += "?" in value
            station_patterns[f"{side}_replacement_character"] += "�" in value
            station_patterns[f"{side}_unbalanced_parentheses"] += (
                value.count("(") != value.count(")") or value.count("（") != value.count("）"))
        fingerprint.add(record)
    observed = {
        "record_count": count, "schema_version": config["schema"],
        "header_present": first_source_row == 2, "first_source_row": first_source_row,
        "last_source_row": last_source_row, "warning_record_count": warning_records,
        "origin_missing": origin_missing, "destination_missing": destination_missing,
        "duration_zero": duration_zero, "duration_gt_24h": duration_gt_24h,
        "duration_gt_7d": duration_gt_7d, "raw_multiset_fingerprint": fingerprint.as_dict(),
        "csv_member": member, "csv_uncompressed_bytes": member_bytes,
        "bike_type_counts": dict(bike_types), "station_patterns": dict(station_patterns),
        "illegal_utf8": {**dict(illegal), "unique_raw_base64_patterns": {
            side: sorted(values) for side, values in illegal_values.items()},
            "unique_raw_base64_pattern_union_count": len(illegal_values["origin"] | illegal_values["destination"])},
    }
    monthly = expected["monthly"]
    gates = {
        "record_count": count == config["records"] == monthly["total_records"],
        "schema": expected["file"]["schema_version"] == config["schema"],
        "header": observed["header_present"] == expected["file"]["header_present"],
        "encoding": ((not monthly["encoding"] and warning_records == 0) or
                     (illegal["illegal_byte_count"] == monthly["encoding"].get("illegal_byte_count") and
                      illegal["affected_field_count"] == monthly["encoding"].get("affected_field_count") and
                      illegal["affected_record_count"] == monthly["encoding"].get("affected_record_count"))),
        "origin_missing": origin_missing == expected_issue_count(monthly, "origin_missing"),
        "destination_missing": destination_missing == expected_issue_count(monthly, "destination_missing"),
        "duration_zero": duration_zero == expected_issue_count(monthly, "duration_zero"),
        "duration_gt_24h": duration_gt_24h == expected_issue_count(monthly, "duration_gt_24h"),
        "duration_gt_7d": duration_gt_7d == expected_issue_count(monthly, "duration_gt_7d"),
        "source_rows": (first_source_row == (2 if expected["file"]["header_present"] else 1) and
                        last_source_row == count + (1 if expected["file"]["header_present"] else 0)),
        "station_patterns": (
            all(station_patterns[key] == value for key, value in monthly["station_patterns"].items()) and
            all(value == 0 for key, value in station_patterns.items() if key not in monthly["station_patterns"])),
        "bike_type": (dict(bike_types) == config["bike_type"] if config["bike_type"] is not None else
                      sum(bike_types.values()) == count and set(bike_types).issubset(OBSERVED_BIKE_TYPES)),
    }
    if schema_evidence_path and config["schema"] == "v2_7col":
        baseline = schema_bike_baseline(schema_evidence_path, config["month"])
        if baseline:
            gates["bike_type_schema_evidence"] = dict(bike_types) == baseline
    if not all(gates.values()):
        raise SourceGateError("preflight differs from Phase 2/3 evidence: " +
                              ",".join(key for key, ok in gates.items() if not ok))
    observed["gates"] = gates
    observed["phase3_repeated_identical"] = monthly["repeated_identical"]
    observed["phase3_station_patterns"] = monthly["station_patterns"]
    return observed


def load_station_universe_csv(path: Path) -> dict[str, dict[str, str]]:
    universe = {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if row["decision"] == "not_an_error":
                if not row["raw_value_base64"] or not row["city"]:
                    raise BatchContractError("malformed not_an_error station-universe row")
                universe[row["raw_value_base64"]] = {
                    "classification": "not_an_error", "station_city": row["city"]}
    return universe


def parser_to_execution(record: dict[str, Any]) -> dict[str, Any]:
    result = dict(record)
    for side in ("origin", "destination"):
        raw = record[f"{side}_station_raw"].encode("utf-8", "surrogateescape")
        result[f"{side}_station_raw_base64"] = base64.b64encode(raw).decode("ascii")
    return result


def parquet_schema():
    import pyarrow as pa
    names = ["borrow_time", "return_time", "duration_raw", "bike_type", "borrow_date",
             "_source_file", "_source_row", "_schema_version", "_parse_warnings"]
    for side in ("origin", "destination"):
        names += [f"{side}_station_raw", f"{side}_station_raw_base64", f"{side}_station_clean",
                  f"{side}_station_id", f"{side}_station_city", f"{side}_station_repair_status",
                  f"{side}_station_rule_version", f"{side}_station_evidence_tier",
                  f"{side}_station_tier1_subtype"]
    return pa.schema([(name, pa.int64() if name == "_source_row" else pa.string()) for name in names])


def _raw_from_cleaned(row: dict[str, Any]) -> dict[str, Any]:
    origin = base64.b64decode(row["origin_station_raw_base64"]).decode("utf-8", "surrogateescape")
    destination = base64.b64decode(row["destination_station_raw_base64"]).decode("utf-8", "surrogateescape")
    return {"borrow_time": row["borrow_time"], "origin_station_raw": origin,
            "return_time": row["return_time"], "destination_station_raw": destination,
            "duration_raw": row["duration_raw"], "bike_type": row["bike_type"],
            "borrow_date": row["borrow_date"]}


def peak_working_set_bytes() -> int | None:
    if os.name != "nt":
        return None
    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
    counters = Counters(); counters.cb = ctypes.sizeof(counters)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    psapi.GetProcessMemoryInfo.argtypes = (ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong)
    psapi.GetProcessMemoryInfo.restype = ctypes.c_int
    ok = psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
    return int(counters.PeakWorkingSetSize) if ok else None


def validate_parquet(path: Path, expected_count: int, input_fingerprint: dict,
                     quarantine_rows: list[int], quarantine_fingerprint: dict[str, Any] | None = None,
                     input_count: int | None = None, expected_bike_types: dict[str, int] | None = None,
                     source_row_min: int = 1, source_row_max: int | None = None) -> dict[str, Any]:
    import pyarrow.parquet as pq
    parquet = pq.ParquetFile(path)
    schema_text = str(parquet.schema_arrow)
    count = 0; null_bike = 0; previous_row = 0; fingerprint = MultisetFingerprint(); bike_types = Counter()
    clean_changes_without_approval = 0; approved_missing_provenance = 0
    nonapproved_identity_assignments = 0
    raw_profile = Counter()
    qset = set(quarantine_rows)
    for batch in parquet.iter_batches(batch_size=BATCH_SIZE):
        for row in batch.to_pylist():
            source_row = row["_source_row"]
            upper = source_row_max if source_row_max is not None else input_count
            if source_row <= previous_row or source_row in qset or source_row < source_row_min or (
                    upper is not None and source_row > upper):
                raise BatchContractError("source-row uniqueness or accepted/quarantine overlap failure")
            previous_row = source_row
            count += 1; null_bike += row["bike_type"] is None
            bike_types["<NULL>" if row["bike_type"] is None else row["bike_type"]] += 1
            if row["origin_station_raw"] is None or row["destination_station_raw"] is None:
                raise BatchContractError("raw station column missing after Parquet round-trip")
            for side in ("origin", "destination"):
                raw_value = base64.b64decode(row[f"{side}_station_raw_base64"]).decode("utf-8", "surrogateescape")
                raw_profile[f"{side}_missing"] += raw_value == ""
                raw_profile[f"{side}_question_mark"] += "?" in raw_value
                raw_profile[f"{side}_replacement_character"] += "�" in raw_value
                raw_profile[f"{side}_unbalanced_parentheses"] += (
                    raw_value.count("(") != raw_value.count(")") or
                    raw_value.count("（") != raw_value.count("）"))
                raw_profile[f"{side}_numeric_suffix"] += bool(SUFFIX_RE.search(raw_value))
                status = row[f"{side}_station_repair_status"]
                changed = row[f"{side}_station_raw"] != row[f"{side}_station_clean"]
                if changed and status != "approved_repair":
                    clean_changes_without_approval += 1
                if status == "approved_repair" and any(row[f"{side}_station_{suffix}"] is None for suffix in
                        ("id", "city", "rule_version", "evidence_tier", "tier1_subtype")):
                    approved_missing_provenance += 1
                if status != "approved_repair" and any(row[f"{side}_station_{suffix}"] is not None for suffix in
                                                        ("id", "rule_version", "evidence_tier", "tier1_subtype")):
                    nonapproved_identity_assignments += 1
            fingerprint.add(_raw_from_cleaned(row))
    parquet.close()
    combined_count = count + len(qset); input_count = input_count if input_count is not None else expected_count
    if count != expected_count or combined_count != input_count:
        raise BatchContractError("Parquet row count or record-conservation validation failed")
    if expected_bike_types is None:
        expected_bike_types = {"<NULL>": count}
    if dict(bike_types) != expected_bike_types:
        raise BatchContractError("bike_type round-trip validation failed")
    accepted_fingerprint = fingerprint.as_dict()
    combined_fingerprint = combine_fingerprints(accepted_fingerprint,
        quarantine_fingerprint or {"count": 0, "sum128": "0" * 32, "xor128": "0" * 32})
    if combined_fingerprint != input_fingerprint:
        raise BatchContractError("raw-record multiset changed during cleaning")
    upper = source_row_max if source_row_max is not None else input_count
    if any(row < source_row_min or row > upper for row in qset) or len(qset) != len(quarantine_rows):
        raise BatchContractError("invalid or duplicate quarantine source rows")
    if clean_changes_without_approval or approved_missing_provenance or nonapproved_identity_assignments:
        raise BatchContractError("station repair invariant failed after Parquet round-trip")
    return {"row_count": count, "bike_type_null_count": null_bike,
            "source_rows_strictly_increasing": True, "accepted_quarantine_overlap": 0,
            "combined_state_count": combined_count,
            "raw_multiset_fingerprint": accepted_fingerprint,
            "combined_multiset_fingerprint": combined_fingerprint,
            "bike_type_counts": dict(bike_types),
            "clean_changes_without_approval": clean_changes_without_approval,
            "approved_missing_provenance": approved_missing_provenance,
            "nonapproved_identity_assignments": nonapproved_identity_assignments,
            "raw_station_profile": dict(raw_profile),
            "schema": schema_text,
            "schema_fingerprint_sha256": hashlib.sha256(schema_text.encode()).hexdigest()}


def run(raw_path: Path, allowlist_path: Path, universe_path: Path, profile_path: Path,
        output_root: Path, receipt_copy: Path, run_id: str, period: str = PERIOD,
        schema_evidence_path: Path | None = None, dry_run: bool = True) -> dict[str, Any]:
    started_dt = datetime.now(timezone.utc); started_clock = time.perf_counter()
    if period not in FULL_PERIOD_MONTHS:
        raise SourceGateError("unsupported bounded dry-run period")
    config = RUN_CONFIGS.get(period) or config_from_profile(profile_path, period)
    preflight_result = preflight(raw_path, profile_path, config, schema_evidence_path)
    rules = load_allowlist(allowlist_path, ALLOWLIST_VERSION)
    universe = load_station_universe_csv(universe_path)
    final_dir = output_root / f"year={config['year']}" / f"month={config['month_number']}"
    if final_dir.exists():
        raise BatchContractError("target dry-run partition already exists")
    final_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=final_dir.parent))
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
        cleaned_path = staging / "cleaned.parquet"; quarantine_path = staging / "quarantine.jsonl"
        writer = pq.ParquetWriter(cleaned_path, parquet_schema(), compression="zstd")
        batch = []; accepted = 0; quarantined = 0; quarantine_rows = []
        side_counts = {side: Counter() for side in ("origin", "destination")}
        trip_counts = Counter(); subtype_counts = Counter()
        quarantine_reasons = Counter(); quarantine_fingerprint = MultisetFingerprint()
        accepted_bike_types = Counter(); quarantine_bike_types = Counter()
        illegal_status = {side: Counter() for side in ("origin", "destination")}
        illegal_approved_records = 0; illegal_quarantined_records = 0
        illegal_approved_sides_accepted = 0
        illegal_quarantine_patterns = set()
        try:
            with quarantine_path.open("w", encoding="utf-8", newline="") as quarantine:
                for record in iter_path(raw_path):
                    adapted = parser_to_execution(record)
                    affected_sides = {("origin" if w["field"] == "origin_station_raw" else "destination")
                                      for w in record["_parse_warnings"]}
                    classified_illegal = {}
                    for side in affected_sides:
                        raw_value = record[f"{side}_station_raw"]
                        result = apply_station_contract(raw_value, rules)
                        status = result["repair_status"]
                        if status == "unchanged_no_rule" and adapted[f"{side}_station_raw_base64"] in universe:
                            status = "not_an_error"
                        classified_illegal[side] = status; illegal_status[side][status] += 1
                    try:
                        cleaned = clean_record(adapted, rules, universe)
                    except (BatchContractError, RepairContractError) as exc:
                        quarantined += 1; quarantine_rows.append(record["_source_row"])
                        quarantine_bike_types["<NULL>" if record["bike_type"] is None else record["bike_type"]] += 1
                        quarantine_reasons[str(exc)] += 1; quarantine_fingerprint.add(record)
                        illegal_quarantined_records += bool(affected_sides)
                        illegal_quarantine_patterns.update(adapted[f"{side}_station_raw_base64"] for side in affected_sides)
                        safe = dict(adapted)
                        for side in ("origin", "destination"):
                            safe[f"{side}_station_raw"] = adapted[f"{side}_station_raw"].encode(
                                "utf-8", "surrogateescape").decode("utf-8", "backslashreplace")
                        quarantine.write(json.dumps({"raw_record": safe, "failure_reason": str(exc),
                            "source_provenance": {key: record[key] for key in
                                ("_source_file", "_source_row", "_schema_version", "_parse_warnings")},
                            "pipeline_version": PIPELINE_VERSION, "allowlist_version": ALLOWLIST_VERSION,
                            "timestamp": started_dt.isoformat()}, ensure_ascii=False, sort_keys=True) + "\n")
                        continue
                    accepted += 1; batch.append(cleaned)
                    accepted_bike_types["<NULL>" if record["bike_type"] is None else record["bike_type"]] += 1
                    illegal_approved_records += any(classified_illegal.get(side) == "approved_repair"
                                                    for side in affected_sides)
                    illegal_approved_sides_accepted += sum(classified_illegal.get(side) == "approved_repair"
                                                           for side in affected_sides)
                    repaired = []
                    for side in ("origin", "destination"):
                        status = cleaned[f"{side}_station_repair_status"]
                        side_counts[side][status] += 1
                        if status == "approved_repair":
                            repaired.append(side)
                            subtype_counts[cleaned[f"{side}_station_tier1_subtype"]] += 1
                    trip_counts[{(): "neither_side_repaired", ("origin",): "origin_only_repaired",
                                 ("destination",): "destination_only_repaired",
                                 ("origin", "destination"): "both_sides_repaired"}[tuple(repaired)]] += 1
                    if len(batch) >= BATCH_SIZE:
                        writer.write_table(pa.Table.from_pylist(batch, schema=parquet_schema())); batch.clear()
                if batch:
                    writer.write_table(pa.Table.from_pylist(batch, schema=parquet_schema())); batch.clear()
        finally:
            writer.close()
        if preflight_result["record_count"] != accepted + quarantined:
            raise BatchContractError("record conservation failure")
        parquet_validation = validate_parquet(cleaned_path, accepted,
            preflight_result["raw_multiset_fingerprint"], quarantine_rows,
            quarantine_fingerprint.as_dict(), preflight_result["record_count"], dict(accepted_bike_types),
            preflight_result["first_source_row"], preflight_result["last_source_row"])
        if sum(side_counts["origin"].values()) != accepted or sum(side_counts["destination"].values()) != accepted:
            raise BatchContractError("station-side count mismatch")
        if sum(trip_counts.values()) != accepted:
            raise BatchContractError("trip-level repair count mismatch")
        elapsed = time.perf_counter() - started_clock
        receipt = {
            "run_id": run_id, "period": period, "dry_run": dry_run,
            "pipeline_version": PIPELINE_VERSION, "parser_version": PARSER_VERSION,
            "allowlist_version": ALLOWLIST_VERSION, "allowlist_sha256": sha256_file(allowlist_path),
            "raw_source": {"filename": raw_path.name, "sha256": sha256_file(raw_path),
                           "bytes": raw_path.stat().st_size, "csv_member": preflight_result["csv_member"],
                           "csv_uncompressed_bytes": preflight_result["csv_uncompressed_bytes"]},
            "input_records": preflight_result["record_count"], "accepted_records": accepted,
            "quarantine_records": quarantined, "record_conservation": accepted + quarantined == preflight_result["record_count"],
            "station_side_status_counts": {side: {status: side_counts[side][status] for status in STATION_STATUSES}
                                           for side in ("origin", "destination")},
            "trip_level_repair_counts": dict(trip_counts),
            "tier1_subtype_station_side_counts": {subtype: subtype_counts[subtype] for subtype in ("1A", "1B", "1C")},
            "repaired_trip_count": accepted - trip_counts["neither_side_repaired"],
            "bike_type_counts": preflight_result["bike_type_counts"],
            "accepted_bike_type_counts": dict(accepted_bike_types),
            "quarantine_bike_type_counts": dict(quarantine_bike_types),
            "illegal_utf8": {**preflight_result["illegal_utf8"],
                "station_side_status_counts": {side: {status: illegal_status[side][status] for status in STATION_STATUSES}
                                               for side in ("origin", "destination")},
                "approved_repair_accepted_station_sides": illegal_approved_sides_accepted,
                "approved_repair_accepted_records": illegal_approved_records,
                "unapproved_quarantine_records": illegal_quarantined_records,
                "unapproved_quarantine_station_sides": sum(count for side in ("origin", "destination")
                    for status, count in illegal_status[side].items() if status != "approved_repair"),
                "quarantine_unique_raw_base64_patterns": sorted(illegal_quarantine_patterns)},
            "quarantine_reason_counts": dict(quarantine_reasons),
            "preflight": preflight_result, "parquet_validation": parquet_validation,
            "phase3_cross_check": {"status": "passed", "profile_sha256": sha256_file(profile_path)},
            "repeated_identical_preservation": {
                **preflight_result["phase3_repeated_identical"], "policy": "retain_all",
                "raw_multiset_fingerprint_match": True},
            "output_hashes": {"cleaned.parquet": sha256_file(cleaned_path),
                              "quarantine.jsonl": sha256_file(quarantine_path)},
            "output_bytes": {"cleaned.parquet": cleaned_path.stat().st_size,
                             "quarantine.jsonl": quarantine_path.stat().st_size},
            "start_timestamp": started_dt.isoformat(), "end_timestamp": datetime.now(timezone.utc).isoformat(),
            "performance": {"wall_clock_seconds": elapsed, "rows_per_second": accepted / elapsed,
                            "peak_working_set_bytes": peak_working_set_bytes()},
            "validation_status": "passed",
        }
        (staging / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(staging, final_dir)
        receipt_copy.parent.mkdir(parents=True, exist_ok=True)
        receipt_copy.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return receipt
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True); parser.add_argument("--allowlist", type=Path, required=True)
    parser.add_argument("--station-universe", type=Path, required=True); parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True); parser.add_argument("--receipt-copy", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--period", choices=FULL_PERIOD_MONTHS, default=PERIOD)
    parser.add_argument("--schema-evidence", type=Path)
    parser.add_argument("--formal", action="store_true", help="mark receipt as formal cleaning, not a dry run")
    args = parser.parse_args()
    # ASCII-safe CLI output works on Windows CP950 terminals even when the ZIP
    # member name contains characters from the archive's legacy filename decode.
    print(json.dumps(run(args.raw, args.allowlist, args.station_universe, args.profile,
                         args.output_root, args.receipt_copy, args.run_id, args.period,
                         args.schema_evidence, not args.formal), ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
