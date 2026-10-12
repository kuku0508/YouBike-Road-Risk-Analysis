"""Build deterministic primary OD counts from Phase 3.7 cleaned partitions."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import statistics
import time
from typing import Any, Iterable

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from profile_od_eligibility import load_identity_evidence, sha256_file

PIPELINE_VERSION = "primary-od-aggregation-v1"
POLICY_VERSION = "od-inclusion-policy-v1"
MONTHS = [f"{year}/{month:02d}" for year in (2023, 2024, 2025)
          for month in range(1, 13) if not (year == 2025 and month > 3)]
EDGE_COLUMNS = ["year", "month", "origin_station_id", "destination_station_id",
                "origin_station_name", "origin_city", "destination_station_name",
                "destination_city", "trip_count"]


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def validate_policy(policy: dict[str, Any]) -> None:
    if policy.get("policy_version") != POLICY_VERSION:
        raise RuntimeError("policy version gate failed")


def load_display_metadata(current_path: Path, historical_path: Path,
                          universe_path: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Current official label wins, then historical snapshot, then station universe."""
    names: dict[str, str] = {}
    cities: dict[str, str] = {}
    with historical_path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            names[row["Station Number"]] = row["Station"]
            cities[row["Station Number"]] = "Taipei"
    for row in json.loads(current_path.read_text(encoding="utf-8")):
        names[row["sno"]] = row["sna"].removeprefix("YouBike2.0_")
        cities[row["sno"]] = "Taipei"
    with universe_path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if row["decision"] == "not_an_error" and row["station_id"]:
                names.setdefault(row["station_id"], row["station_name"] or row["raw_station_value"])
                cities.setdefault(row["station_id"], row["city"])
    return names, cities


def resolve_endpoint(frame: pd.DataFrame, side: str, evidence: dict[str, Any]) -> pd.Series:
    status = frame[f"{side}_station_repair_status"].fillna("")
    raw = frame[f"{side}_station_raw"].fillna("")
    raw_b64 = frame[f"{side}_station_raw_base64"].fillna("")
    supplied = frame[f"{side}_station_id"].fillna("")
    resolved = pd.Series(pd.NA, index=frame.index, dtype="string")
    approved = status.eq("approved_repair") & supplied.ne("") & raw.ne("")
    resolved.loc[approved] = supplied.loc[approved]
    not_error = status.eq("not_an_error") & raw.ne("")
    universe = {key: value[0] for key, value in evidence["station_universe"].items()}
    resolved.loc[not_error] = raw_b64.loc[not_error].map(universe).astype("string")
    unchanged = status.eq("unchanged_no_rule") & raw.ne("")
    names = {key: value[0] for key, value in evidence["unique_names"].items()}
    resolved.loc[unchanged] = raw.loc[unchanged].map(names).astype("string")
    return resolved


def aggregate_frames(frames: Iterable[pd.DataFrame], evidence: dict[str, Any], year: int,
                     month: int) -> tuple[pd.DataFrame, dict[str, Any], dict[str, set[str]]]:
    counts: Counter[tuple[str, str]] = Counter()
    labels: dict[str, set[str]] = defaultdict(set)
    input_rows = eligible_rows = 0
    for frame in frames:
        input_rows += len(frame)
        origin = resolve_endpoint(frame, "origin", evidence)
        destination = resolve_endpoint(frame, "destination", evidence)
        eligible = origin.notna() & destination.notna()
        eligible_rows += int(eligible.sum())
        pairs = pd.DataFrame({"origin": origin[eligible], "destination": destination[eligible]})
        grouped = pairs.value_counts(sort=False)
        counts.update({(str(key[0]), str(key[1])): int(value) for key, value in grouped.items()})
        for side, ids in (("origin", origin), ("destination", destination)):
            subset = pd.DataFrame({"id": ids[eligible], "label": frame.loc[eligible, f"{side}_station_clean"]})
            for station_id, values in subset.dropna().groupby("id", sort=False)["label"]:
                labels[str(station_id)].update(str(v) for v in values.unique() if str(v))
    rows = [(year, month, origin, destination, count)
            for (origin, destination), count in sorted(counts.items())]
    edges = pd.DataFrame(rows, columns=["year", "month", "origin_station_id",
                                        "destination_station_id", "trip_count"])
    self_mask = edges["origin_station_id"].eq(edges["destination_station_id"])
    stats = {"input_cleaned_records": input_rows, "eligible_trip_count": eligible_rows,
             "od_edge_count": len(edges), "unique_origin_nodes": int(edges["origin_station_id"].nunique()),
             "unique_destination_nodes": int(edges["destination_station_id"].nunique()),
             "self_loop_trips": int(edges.loc[self_mask, "trip_count"].sum()),
             "self_loop_edges": int(self_mask.sum())}
    return edges, stats, labels


def add_display_columns(edges: pd.DataFrame, names: dict[str, str], cities: dict[str, str]) -> pd.DataFrame:
    result = edges.copy()
    result["origin_station_name"] = result["origin_station_id"].map(names)
    result["origin_city"] = result["origin_station_id"].map(cities)
    result["destination_station_name"] = result["destination_station_id"].map(names)
    result["destination_city"] = result["destination_station_id"].map(cities)
    return result[EDGE_COLUMNS]


def edge_statistics(edges: pd.DataFrame) -> dict[str, Any]:
    values = edges["trip_count"]
    self_mask = edges["origin_station_id"].eq(edges["destination_station_id"])
    nodes = set(edges["origin_station_id"]) | set(edges["destination_station_id"])
    return {"total_trip_count": int(values.sum()), "edge_count": len(edges), "node_count": len(nodes),
            "origin_node_count": int(edges["origin_station_id"].nunique()),
            "destination_node_count": int(edges["destination_station_id"].nunique()),
            "trip_count_min": int(values.min()), "trip_count_median": float(values.median()),
            "trip_count_mean": float(values.mean()), "trip_count_max": int(values.max()),
            "self_loop_trips": int(edges.loc[self_mask, "trip_count"].sum()),
            "self_loop_edges": int(self_mask.sum())}


def combine_edges(paths: list[Path], year: int = 0, month: int = 0) -> pd.DataFrame:
    # ParquetFile avoids dataset-level Hive inference from year=/month= directories.
    frames = [pq.ParquetFile(path).read().to_pandas() for path in paths]
    combined = pd.concat(frames, ignore_index=True)
    keys = ["origin_station_id", "destination_station_id"]
    result = combined.groupby(keys, as_index=False, sort=True)["trip_count"].sum()
    result.insert(0, "month", month); result.insert(0, "year", year)
    for side in ("origin", "destination"):
        label_map = combined.groupby(f"{side}_station_id", sort=True).first()
        result[f"{side}_station_name"] = result[f"{side}_station_id"].map(label_map[f"{side}_station_name"])
        result[f"{side}_city"] = result[f"{side}_station_id"].map(label_map[f"{side}_city"])
    return result[EDGE_COLUMNS].sort_values(["origin_station_id", "destination_station_id"]).reset_index(drop=True)


def write_parquet(edges: pd.DataFrame, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(edges, preserve_index=False)
    pq.write_table(table, path, compression="zstd", write_statistics=True)
    return sha256_file(path)


def build_node_inventory(full_edges: pd.DataFrame, monthly_edges: list[tuple[str, pd.DataFrame]],
                         names: dict[str, str], cities: dict[str, str]) -> pd.DataFrame:
    nodes = sorted(set(full_edges.origin_station_id) | set(full_edges.destination_station_id))
    first: dict[str, str] = {}; last: dict[str, str] = {}; origin_seen = set(); destination_seen = set()
    for period, edges in monthly_edges:
        origins = set(edges.origin_station_id); destinations = set(edges.destination_station_id)
        origin_seen |= origins; destination_seen |= destinations
        for station_id in origins | destinations:
            first.setdefault(station_id, period); last[station_id] = period
    outgoing = full_edges.groupby("origin_station_id").trip_count.sum().to_dict()
    incoming = full_edges.groupby("destination_station_id").trip_count.sum().to_dict()
    return pd.DataFrame([{ "station_id": node, "canonical_name": names.get(node), "city": cities.get(node),
                           "observed_as_origin": node in origin_seen, "observed_as_destination": node in destination_seen,
                           "first_observed_month": first[node], "last_observed_month": last[node],
                           "total_outgoing_trips": int(outgoing.get(node, 0)),
                           "total_incoming_trips": int(incoming.get(node, 0))} for node in nodes])


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter(); started_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    sampled_peak_memory = _current_memory()
    policy = _json(args.policy)
    validate_policy(policy)
    impact = _json(args.impact); cleaning = _json(args.cleaning_manifest)
    evidence = load_identity_evidence(args.current_metadata, args.historical_metadata,
                                      args.station_universe, args.metadata_evidence)
    names, cities = load_display_metadata(args.current_metadata, args.historical_metadata, args.station_universe)
    expected_month = {row["month"]: row for row in cleaning["monthly"]}
    staging = args.output_root.parent / f".{args.output_root.name}.staging"
    if staging.exists(): shutil.rmtree(staging)
    staging.mkdir(parents=True)
    monthly_receipts = []; monthly_paths = []; monthly_tables = []; all_labels: dict[str, set[str]] = defaultdict(set)
    try:
        for period in MONTHS:
            month_started = time.perf_counter(); year, month = map(int, period.split("/"))
            source = args.cleaned_root / f"year={year}" / f"month={month:02d}" / "cleaned.parquet"
            expected = expected_month[period]
            if sha256_file(source) != expected["cleaned_output_sha256"]:
                raise RuntimeError(f"source cleaned hash mismatch: {period}")
            pf = pq.ParquetFile(source)
            columns = []
            for side in ("origin", "destination"):
                columns += [f"{side}_station_raw", f"{side}_station_raw_base64", f"{side}_station_clean",
                            f"{side}_station_id", f"{side}_station_repair_status"]
            frames = (batch.to_pandas() for batch in pf.iter_batches(batch_size=262_144, columns=columns))
            edges, stats, labels = aggregate_frames(frames, evidence, year, month)
            expected_eligible = impact["monthly"][period]["primary_id_required_full_universe"]
            if stats["input_cleaned_records"] != expected["accepted_records"] or stats["eligible_trip_count"] != expected_eligible:
                raise RuntimeError(f"monthly conservation failed: {period}")
            edges = add_display_columns(edges, names, cities)
            path = staging / "monthly" / f"year={year}" / f"month={month:02d}" / "od.parquet"
            output_hash = write_parquet(edges, path)
            if int(edges.trip_count.sum()) != expected_eligible:
                raise RuntimeError(f"monthly OD sum failed: {period}")
            for station_id, values in labels.items(): all_labels[station_id].update(values)
            receipt = {"month": period, **stats, "self_loop_trip_proportion": stats["self_loop_trips"] / expected_eligible,
                       "output_sha256": output_hash, "output_bytes": path.stat().st_size,
                       "source_cleaned_partition_sha256": expected["cleaned_output_sha256"],
                       "policy_version": POLICY_VERSION, "wall_clock_seconds": time.perf_counter() - month_started,
                       "validation_status": "passed"}
            monthly_receipts.append(receipt); monthly_paths.append(path); monthly_tables.append((period, edges))
            current_memory = _current_memory()
            if current_memory is not None:
                sampled_peak_memory = max(sampled_peak_memory or 0, current_memory)
        periods = {"2023": monthly_paths[:12], "2024": monthly_paths[12:24],
                   "core_2023_2024": monthly_paths[:24], "full_2023_2025_03": monthly_paths}
        aggregate_receipts = []
        aggregate_tables = {}
        for label, paths in periods.items():
            edges = combine_edges(paths); aggregate_tables[label] = edges
            path = staging / "aggregate" / label / "od.parquet"
            output_hash = write_parquet(edges, path); stats = edge_statistics(edges)
            aggregate_receipts.append({"period": label, **stats, "self_loop_trip_proportion": stats["self_loop_trips"] / stats["total_trip_count"],
                                       "output_sha256": output_hash, "output_bytes": path.stat().st_size,
                                       "policy_version": POLICY_VERSION, "validation_status": "passed"})
        full = aggregate_tables["full_2023_2025_03"]
        if int(full.trip_count.sum()) != impact["precedence_resolved_counts"]["od_eligible"]:
            raise RuntimeError("full-period OD conservation failed")
        core_expected = sum(impact["monthly"][m]["primary_id_required_full_universe"] for m in MONTHS[:24])
        if int(aggregate_tables["core_2023_2024"].trip_count.sum()) != core_expected:
            raise RuntimeError("core-period OD conservation failed")
        node_inventory = build_node_inventory(full, monthly_tables, names, cities)
        node_path = staging / "node_inventory.parquet"; node_hash = write_parquet(node_inventory, node_path)
        conflicts = {station_id: sorted(values) for station_id, values in all_labels.items() if len(values) > 1}
        city_counts = Counter()
        for row in full.itertuples(index=False): city_counts[f"{row.origin_city or 'Other'}->{row.destination_city or 'Other'}"] += int(row.trip_count)
        exclusion = {"policy_version": POLICY_VERSION, "scope": impact["scope"],
                     "total_input_records": impact["total_input_records"],
                     "eligible_records": impact["precedence_resolved_counts"]["od_eligible"],
                     "excluded_union": impact["total_input_records"] - impact["precedence_resolved_counts"]["od_eligible"],
                     "precedence": policy["exclusion_precedence"],
                     "categories": [{"category": key, "record_count": value,
                                     "proportion": value / impact["total_input_records"],
                                     "precedence": policy["exclusion_precedence"].index(key) + 1,
                                     "primary_reason": key,
                                     "status": "excluded_from_primary_od"}
                                    for key, value in impact["precedence_resolved_counts"].items() if key != "od_eligible"],
                     "secondary_flags": impact["trip_flag_counts"], "overlap_matrix": impact["issue_overlap_matrix"],
                     "conservation_passed": sum(impact["precedence_resolved_counts"].values()) == impact["total_input_records"]}
        manifest = {"pipeline_version": PIPELINE_VERSION, "policy_version": POLICY_VERSION, "scope": impact["scope"],
                    "status": "complete", "started_at": started_at, "completed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "monthly": monthly_receipts, "aggregates": aggregate_receipts,
                    "core_eligible_trip_count": core_expected,
                    "full_eligible_trip_count": int(full.trip_count.sum()),
                    "city_flow_counts": dict(sorted(city_counts.items())),
                    "label_conflict_count": len(conflicts), "label_conflicts": conflicts,
                    "node_inventory": {"row_count": len(node_inventory), "output_sha256": node_hash,
                                       "output_bytes": node_path.stat().st_size},
                    "source_hashes": {"policy": sha256_file(args.policy), "impact": sha256_file(args.impact),
                                      "cleaning_manifest": sha256_file(args.cleaning_manifest), **evidence["source_hashes"]},
                    "performance": {"total_wall_clock_seconds": time.perf_counter() - started,
                                    "approximate_peak_working_set_bytes": sampled_peak_memory,
                                    "memory_measurement": "process RSS sampled after each monthly partition",
                                    "monthly_output_bytes": sum(r["output_bytes"] for r in monthly_receipts),
                                    "aggregate_output_bytes": sum(r["output_bytes"] for r in aggregate_receipts)},
                    "validation": {"month_count_27": len(monthly_receipts) == 27,
                                   "monthly_all_passed": all(r["validation_status"] == "passed" for r in monthly_receipts),
                                   "full_conservation": int(full.trip_count.sum()) == 108077420,
                                   "eligible_plus_excluded_equals_input": exclusion["eligible_records"] + exclusion["excluded_union"] == exclusion["total_input_records"],
                                   "deterministic_sort": True, "network_metrics_computed": False}}
        _write_json(args.manifest_output, manifest); _write_json(args.exclusion_output, exclusion)
        if args.output_root.exists(): shutil.rmtree(args.output_root)
        os.replace(staging, args.output_root)
        return manifest
    except Exception:
        if staging.exists(): shutil.rmtree(staging)
        raise


def _current_memory() -> int | None:
    try:
        import psutil
        return psutil.Process().memory_info().rss
    except (ImportError, AttributeError):
        pass
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            class Counters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                            ("PrivateUsage", ctypes.c_size_t)]
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
            psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
            counters = Counters(); counters.cb = ctypes.sizeof(counters)
            handle = kernel32.GetCurrentProcess()
            if psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                return int(counters.PeakWorkingSetSize)
        except (AttributeError, OSError):
            pass
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--cleaned-root", type=Path, default=root / "data/processed/cleaned")
    parser.add_argument("--output-root", type=Path, default=root / "data/processed/od")
    parser.add_argument("--policy", type=Path, default=root / "config/od_inclusion_policy.yaml")
    parser.add_argument("--impact", type=Path, default=root / "notes/od-inclusion-impact.json")
    parser.add_argument("--cleaning-manifest", type=Path, default=root / "notes/full-period-cleaning-manifest.json")
    parser.add_argument("--current-metadata", type=Path, default=root / "data/raw/youbike_immediate_2026-09-13.json")
    parser.add_argument("--historical-metadata", type=Path, default=root / "data/raw/station_snapshot_2024-05-31.csv")
    parser.add_argument("--station-universe", type=Path, default=root / "notes/station-universe-classification.csv")
    parser.add_argument("--metadata-evidence", type=Path, default=root / "notes/station-metadata-evidence.json")
    parser.add_argument("--manifest-output", type=Path, default=root / "notes/od-aggregation-manifest.json")
    parser.add_argument("--exclusion-output", type=Path, default=root / "notes/od-exclusion-audit.json")
    args = parser.parse_args(); result = run(args)
    print(json.dumps({"status": result["status"], "full": result["full_eligible_trip_count"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
