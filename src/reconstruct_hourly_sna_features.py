"""Reconstruct 2023-2024 weekday/holiday hourly SNA features without clustering."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Any, Iterable

import networkx as nx
import igraph as ig
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from aggregate_primary_od import load_display_metadata, resolve_endpoint
from profile_od_eligibility import load_identity_evidence, sha256_file

PIPELINE_VERSION = "hourly-sna-feature-reconstruction-v1"
DAY_TYPES = ("weekday", "holiday")
METRICS = ("betweenness", "eigenvector", "pagerank")
CORE_MONTHS = [f"{year}/{month:02d}" for year in (2023, 2024) for month in range(1, 13)]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def hash_value(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def load_contract(path: Path) -> dict[str, Any]:
    value = read_json(path)
    if value.get("contract_version") != PIPELINE_VERSION:
        raise RuntimeError("unknown hourly SNA contract")
    if value.get("analysis_period") != "2023-01-01/2024-12-31":
        raise RuntimeError("period gate failed")
    if value["input"].get("expected_eligible_trips") != 91_138_763:
        raise RuntimeError("eligible-trip gate failed")
    if value["features"] != {"metrics": list(METRICS), "hours": list(range(24)),
                              "feature_count": 72, "scaling": "none_in_phase_7_3"}:
        raise RuntimeError("feature contract mismatch")
    if value["metrics"]["betweenness"].get("exact") is not True:
        raise RuntimeError("approximate betweenness is forbidden")
    if value["station_universe"].get("expected_node_count") != 2782:
        raise RuntimeError("station-universe gate failed")
    return value


def load_calendar(fst_path: Path, expected_hash: str, rscript: Path, exporter: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    observed_hash = sha256_file(fst_path)
    if observed_hash != expected_hash:
        raise RuntimeError("calendar SHA-256 mismatch")
    with tempfile.TemporaryDirectory(prefix="youbike-calendar-") as folder:
        csv_path = Path(folder) / "calendar.csv"
        subprocess.run([str(rscript), str(exporter), str(fst_path), str(csv_path)], check=True,
                       capture_output=True, text=True)
        frame = pd.read_csv(csv_path)
    if list(frame.columns) != ["Date", "IsHoliday", "NaturalDisaster"]:
        raise RuntimeError("calendar schema mismatch")
    frame["Date"] = pd.to_datetime(frame["Date"], errors="raise").dt.date
    for column in ("IsHoliday", "NaturalDisaster"):
        if frame[column].isna().any() or set(frame[column].unique()) - {0, 1}:
            raise RuntimeError(f"calendar {column} must be complete numeric 0/1")
        frame[column] = frame[column].astype("int8")
    if frame.Date.duplicated().any():
        raise RuntimeError("calendar contains duplicate Date")
    all_dates = pd.date_range(frame.Date.min(), frame.Date.max(), freq="D").date
    missing_all = sorted(set(all_dates) - set(frame.Date))
    core_dates = pd.date_range("2023-01-01", "2024-12-31", freq="D").date
    missing_core = sorted(set(core_dates) - set(frame.Date))
    if missing_all or missing_core:
        raise RuntimeError("calendar date coverage incomplete")
    core = frame[frame.Date.isin(core_dates)].copy()
    audit = {
        "source_filename": fst_path.name, "source_sha256": observed_hash,
        "source_bytes": fst_path.stat().st_size, "schema": {"Date": "R Date",
        "IsHoliday": "numeric 0/1", "NaturalDisaster": "numeric 0/1"},
        "date_min": str(frame.Date.min()), "date_max": str(frame.Date.max()),
        "total_dates": len(frame), "core_dates": len(core),
        "dates_2023": int(sum(date.year == 2023 for date in core.Date)),
        "dates_2024": int(sum(date.year == 2024 for date in core.Date)),
        "holiday_dates": int(core.IsHoliday.sum()), "weekday_dates": int((core.IsHoliday == 0).sum()),
        "natural_disaster_dates": int(core.NaturalDisaster.sum()),
        "missing_dates": [], "duplicate_dates": 0, "unknown_is_holiday_values": [],
        "natural_disaster_override_applied": False, "validation_status": "passed",
    }
    return core, audit


def extract_hour(values: pd.Series) -> pd.Series:
    text = values.astype("string")
    full_timestamp = text.str.match(r"^\d{4}-\d{2}-\d{2} ([01]\d|2[0-3]):00:00$")
    hour_only = text.str.match(r"^([01]?\d|2[0-3])(?::00(?::00)?)?$")
    if not (full_timestamp | hour_only).all():
        raise RuntimeError("borrow_time representation is outside the parser contract")
    hour = pd.to_numeric(text.str.extract(r"(?:^| )(\d{1,2})(?::00(?::00)?$|$)", expand=False), errors="coerce")
    if hour.isna().any() or not hour.between(0, 23).all():
        raise RuntimeError("borrow_time cannot be mapped exactly to hour 0..23")
    return hour.astype("int8")


def aggregate_hourly(cleaned_root: Path, calendar: pd.DataFrame, evidence: dict[str, Any],
                     cleaning_manifest: dict[str, Any], impact: dict[str, Any]) -> tuple[dict[tuple[str, int], Counter], dict[str, Any]]:
    calendar_map = dict(zip(calendar.Date, calendar.IsHoliday, strict=True))
    counters = {(day, hour): Counter() for day in DAY_TYPES for hour in range(24)}
    bucket_dates = {(day, hour): set() for day in DAY_TYPES for hour in range(24)}
    total = 0; repeated_preserved = True
    expected_month = {row["month"]: row for row in cleaning_manifest["monthly"]}
    columns = ["borrow_date", "borrow_time"]
    for side in ("origin", "destination"):
        columns += [f"{side}_station_raw", f"{side}_station_raw_base64", f"{side}_station_clean",
                    f"{side}_station_id", f"{side}_station_repair_status"]
    for period in CORE_MONTHS:
        year, month = map(int, period.split("/"))
        path = cleaned_root / f"year={year}" / f"month={month:02d}" / "cleaned.parquet"
        if sha256_file(path) != expected_month[period]["cleaned_output_sha256"]:
            raise RuntimeError(f"cleaned input hash mismatch: {period}")
        month_total = 0
        for batch in pq.ParquetFile(path).iter_batches(batch_size=262_144, columns=columns):
            frame = batch.to_pandas()
            origin = resolve_endpoint(frame, "origin", evidence)
            destination = resolve_endpoint(frame, "destination", evidence)
            eligible = origin.notna() & destination.notna()
            if not eligible.any():
                continue
            dates = pd.to_datetime(frame.loc[eligible, "borrow_date"], errors="raise").dt.date
            mapped = dates.map(calendar_map)
            if mapped.isna().any():
                raise RuntimeError("eligible trip date did not match exactly one calendar row")
            hours = extract_hour(frame.loc[eligible, "borrow_time"])
            time_dates = pd.to_datetime(frame.loc[eligible, "borrow_time"], errors="raise").dt.date
            if not (time_dates == dates).all():
                raise RuntimeError("borrow_time date and borrow_date disagree")
            selected = pd.DataFrame({"origin": origin[eligible].astype(str),
                                     "destination": destination[eligible].astype(str),
                                     "date": dates, "hour": hours,
                                     "day_type": mapped.map({0: "weekday", 1: "holiday"})})
            for (day_type, hour), part in selected.groupby(["day_type", "hour"], sort=False):
                grouped = part[["origin", "destination"]].value_counts(sort=False)
                counters[(str(day_type), int(hour))].update({(str(key[0]), str(key[1])): int(value)
                                                              for key, value in grouped.items()})
                bucket_dates[(str(day_type), int(hour))].update(part.date.unique())
            count = len(selected); total += count; month_total += count
        expected = impact["monthly"][period]["primary_id_required_full_universe"]
        if month_total != expected:
            raise RuntimeError(f"monthly eligible conservation failed: {period}")
    if total != 91_138_763 or sum(sum(c.values()) for c in counters.values()) != total:
        raise RuntimeError("48-bucket trip conservation failed")
    return counters, {"total_eligible_trips": total, "repeated_records_preserved": repeated_preserved,
                      "bucket_source_dates": {f"{d}-{h:02d}": len(bucket_dates[(d, h)])
                                              for d in DAY_TYPES for h in range(24)}}


def counter_to_edges(counter: Counter) -> pd.DataFrame:
    rows = [(u, v, int(weight)) for (u, v), weight in sorted(counter.items())]
    return pd.DataFrame(rows, columns=["origin_station_id", "destination_station_id", "trip_count"])


def persist_hourly_od(counters: dict[tuple[str, int], Counter], output_root: Path,
                      identity: dict[str, Any], conservation: dict[str, Any]) -> dict[str, Any]:
    buckets = []
    for day_type in DAY_TYPES:
        for hour in range(24):
            path = output_root / f"day_type={day_type}" / f"hour={hour:02d}" / "od.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            edges = counter_to_edges(counters[(day_type, hour)])
            tmp = path.with_suffix(".tmp.parquet")
            pq.write_table(pa.Table.from_pandas(edges, preserve_index=False), tmp, compression="zstd")
            os.replace(tmp, path)
            buckets.append({"day_type": day_type, "hour": hour, "trip_count": int(edges.trip_count.sum()),
                            "edge_count": len(edges), "sha256": sha256_file(path),
                            "path": str(path.relative_to(output_root)).replace("\\", "/")})
    manifest = {"identity": identity, "conservation": conservation, "buckets": buckets,
                "bucket_count": 48, "validation_status": "passed"}
    write_json(output_root / "hourly-od-checkpoint.json", manifest)
    return manifest


def load_hourly_od(output_root: Path, identity: dict[str, Any]) -> tuple[dict[tuple[str, int], Counter], dict[str, Any]] | None:
    manifest_path = output_root / "hourly-od-checkpoint.json"
    if not manifest_path.exists(): return None
    manifest = read_json(manifest_path)
    if manifest.get("identity") != identity or manifest.get("bucket_count") != 48: return None
    counters = {}
    for item in manifest["buckets"]:
        path = output_root / item["path"]
        if not path.exists() or sha256_file(path) != item["sha256"]: return None
        edges = pq.ParquetFile(path).read().to_pandas()
        counters[(item["day_type"], int(item["hour"]))] = Counter({(str(r.origin_station_id), str(r.destination_station_id)): int(r.trip_count)
                                                                    for r in edges.itertuples(index=False)})
    if sum(sum(counter.values()) for counter in counters.values()) != 91_138_763: return None
    return counters, manifest["conservation"]


def graph_from_edges(edges: pd.DataFrame, nodes: list[str]) -> nx.DiGraph:
    graph = nx.DiGraph(); graph.add_nodes_from(nodes)
    graph.add_weighted_edges_from(edges.itertuples(index=False, name=None), weight="trip_count")
    return graph


def graph_fingerprint(edges: pd.DataFrame, nodes: list[str]) -> str:
    digest = hashlib.sha256(("\n".join(nodes) + "\n").encode())
    for row in edges.itertuples(index=False):
        digest.update(f"{row.origin_station_id}\t{row.destination_station_id}\t{row.trip_count}\n".encode())
    return digest.hexdigest()


def exact_directed_betweenness_igraph(edges: pd.DataFrame, nodes: list[str]) -> dict[str, float]:
    """Exact Brandes betweenness with NetworkX directed normalization semantics."""
    node_index = {node: index for index, node in enumerate(nodes)}
    pairs = [(node_index[str(row.origin_station_id)], node_index[str(row.destination_station_id)])
             for row in edges.itertuples(index=False) if row.origin_station_id != row.destination_station_id]
    graph = ig.Graph(n=len(nodes), edges=pairs, directed=True)
    raw = graph.betweenness(directed=True, weights=None)
    scale = 0.0 if len(nodes) <= 2 else 1.0 / ((len(nodes) - 1) * (len(nodes) - 2))
    return {node: float(raw[index]) * scale for index, node in enumerate(nodes)}


def checkpoint_metric(name: str, nodes: list[str], folder: Path, identity: dict[str, Any],
                      compute) -> tuple[pd.Series, dict[str, Any]]:
    path = folder / f"{name}.parquet"; meta_path = folder / f"{name}.json"
    if path.exists() and meta_path.exists():
        meta = read_json(meta_path)
        if meta.get("identity") == identity and meta.get("output_sha256") == sha256_file(path):
            values = pq.ParquetFile(path).read().to_pandas().set_index("station_id")[name].reindex(nodes)
            if values.notna().all() and np.isfinite(values.to_numpy()).all():
                return values, meta
    started = time.perf_counter(); raw = compute(); runtime = time.perf_counter() - started
    values = pd.Series(raw, dtype=float, name=name).reindex(nodes, fill_value=0.0)
    if values.isna().any() or not np.isfinite(values.to_numpy()).all():
        raise RuntimeError(f"{name} contains NaN or Inf")
    folder.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.parquet")
    pq.write_table(pa.Table.from_pandas(values.rename_axis("station_id").reset_index(), preserve_index=False), tmp,
                   compression="zstd")
    os.replace(tmp, path)
    meta = {"identity": identity, "runtime_seconds": runtime, "output_sha256": sha256_file(path),
            "validation_status": "passed"}
    write_json(meta_path, meta)
    return values, meta


def compute_bucket(day_type: str, hour: int, edges: pd.DataFrame, nodes: list[str], output_root: Path,
                   base_identity: dict[str, Any], source_date_count: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    folder = output_root / f"day_type={day_type}" / f"hour={hour:02d}"
    graph_hash = graph_fingerprint(edges, nodes)
    identity = {**base_identity, "day_type": day_type, "hour": hour, "graph_sha256": graph_hash}
    graph = graph_from_edges(edges, nodes)
    no_loops = graph.copy(); no_loops.remove_edges_from(nx.selfloop_edges(no_loops))
    active = sorted(node for node in no_loops if no_loops.in_degree(node) + no_loops.out_degree(node) > 0)
    active_graph = no_loops.subgraph(active).copy()
    bet, bet_meta = checkpoint_metric("betweenness", nodes, folder,
        {**identity, "metric": "betweenness", "backend": "python-igraph", "backend_version": ig.__version__},
        lambda: exact_directed_betweenness_igraph(edges, nodes))
    def eigenvector_values() -> dict[str, float]:
        if not active:
            return {node: 0.0 for node in nodes}
        values = nx.eigenvector_centrality(active_graph, max_iter=1000, tol=1e-9, weight=None)
        return {node: float(values.get(node, 0.0)) for node in nodes}
    eig, eig_meta = checkpoint_metric("eigenvector", nodes, folder, {**identity, "metric": "eigenvector"},
                                      eigenvector_values)
    pr, pr_meta = checkpoint_metric("pagerank", nodes, folder, {**identity, "metric": "pagerank"},
        lambda: nx.pagerank(graph, alpha=0.85, weight="trip_count", max_iter=1000, tol=1e-9))
    metrics = pd.DataFrame({"station_id": nodes, "betweenness": bet.to_numpy(),
                            "eigenvector": eig.to_numpy(), "pagerank": pr.to_numpy()})
    validations = {
        "node_count_2782": len(metrics) == 2782, "station_id_unique": metrics.station_id.is_unique,
        "finite": bool(np.isfinite(metrics[list(METRICS)].to_numpy()).all()),
        "betweenness_range": bool(metrics.betweenness.between(0, 1).all()),
        "eigenvector_nonnegative": bool((metrics.eigenvector >= 0).all()),
        "eigenvector_active_norm": abs(float(np.square(metrics.eigenvector).sum()) - 1.0) <= 1e-6,
        "eigenvector_isolates_zero": bool((metrics.loc[~metrics.station_id.isin(active), "eigenvector"] == 0).all()),
        "pagerank_nonnegative": bool((metrics.pagerank >= 0).all()),
        "pagerank_sum": abs(float(metrics.pagerank.sum()) - 1.0) <= 1e-8,
    }
    if not all(validations.values()):
        raise RuntimeError(f"hourly metric validation failed: {day_type}/{hour}: {validations}")
    metric_path = folder / "metrics.parquet"; edge_path = folder / "od.parquet"
    pq.write_table(pa.Table.from_pandas(metrics, preserve_index=False), metric_path, compression="zstd")
    if not edge_path.exists():
        pq.write_table(pa.Table.from_pandas(edges, preserve_index=False), edge_path, compression="zstd")
    self_mask = edges.origin_station_id.eq(edges.destination_station_id)
    receipt = {"day_type": day_type, "hour": hour, "trip_count": int(edges.trip_count.sum()),
               "edge_count": len(edges), "node_count": len(nodes), "active_node_count": len(active),
               "active_origin_nodes": int(edges.origin_station_id.nunique()),
               "active_destination_nodes": int(edges.destination_station_id.nunique()),
               "self_loop_trips": int(edges.loc[self_mask, "trip_count"].sum()),
               "source_date_count": source_date_count, "graph_sha256": graph_hash,
               "metric_output_hashes": {name: meta["output_sha256"] for name, meta in
                                         (("betweenness", bet_meta), ("eigenvector", eig_meta), ("pagerank", pr_meta))},
               "metric_runtimes_seconds": {name: meta["runtime_seconds"] for name, meta in
                                            (("betweenness", bet_meta), ("eigenvector", eig_meta), ("pagerank", pr_meta))},
               "metrics_parquet_sha256": sha256_file(metric_path), "od_parquet_sha256": sha256_file(edge_path),
               "eigenvector_convergence": "converged", "validation": validations,
               "validation_status": "passed"}
    write_json(folder / "receipt.json", receipt)
    return metrics, receipt


def assemble_matrix(day_type: str, bucket_metrics: dict[tuple[str, int], pd.DataFrame], inventory: pd.DataFrame,
                    output_root: Path) -> tuple[Path, dict[str, Any]]:
    base = inventory[["station_id", "canonical_name", "city"]].rename(columns={"canonical_name": "station_name"}).copy()
    for metric in METRICS:
        for hour in range(24):
            frame = bucket_metrics[(day_type, hour)].set_index("station_id")
            base[f"{metric}_h{hour:02d}"] = base.station_id.map(frame[metric])
    feature_columns = [f"{metric}_h{hour:02d}" for metric in METRICS for hour in range(24)]
    if len(base) != 2782 or list(base.columns[3:]) != feature_columns:
        raise RuntimeError("72-feature matrix shape/columns failed")
    if base.station_id.duplicated().any() or base[feature_columns].isna().any().any() or not np.isfinite(base[feature_columns]).all().all():
        raise RuntimeError("72-feature matrix numerical gate failed")
    path = output_root / f"hierarchical_{day_type}_72_features.parquet"
    pq.write_table(pa.Table.from_pandas(base, preserve_index=False), path, compression="zstd")
    return path, {"shape": [len(base), len(feature_columns)], "parquet_columns": len(base.columns),
                  "sha256": sha256_file(path), "bytes": path.stat().st_size,
                  "station_order_sha256": hashlib.sha256("\n".join(base.station_id).encode()).hexdigest(),
                  "no_nan": True, "all_finite": True, "scaling_applied": False}


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter(); contract = load_contract(args.contract)
    previous_manifest = read_json(args.manifest) if args.manifest.exists() else None
    calendar, calendar_audit = load_calendar(args.calendar, contract["calendar"]["sha256"], args.rscript, args.calendar_exporter)
    write_json(args.calendar_audit, calendar_audit)
    cleaning = read_json(args.cleaning_manifest); impact = read_json(args.impact)
    evidence = load_identity_evidence(args.current_metadata, args.historical_metadata,
                                      args.station_universe_evidence, args.metadata_evidence)
    cleaned_hashes = {row["month"]: row["cleaned_output_sha256"] for row in cleaning["monthly"]
                      if row["month"] in CORE_MONTHS}
    od_identity = {"pipeline_version": PIPELINE_VERSION, "calendar_sha256": calendar_audit["source_sha256"],
                   "od_policy_version": "od-inclusion-policy-v1", "contract_sha256": sha256_file(args.contract),
                   "cleaned_partition_hashes_sha256": hash_value(cleaned_hashes)}
    cached = load_hourly_od(args.output_root, od_identity)
    if cached is None:
        counters, conservation = aggregate_hourly(args.cleaned_root, calendar, evidence, cleaning, impact)
        persist_hourly_od(counters, args.output_root, od_identity, conservation)
    else:
        counters, conservation = cached
    core_od = pq.ParquetFile(args.core_od).read().to_pandas()
    nodes = sorted(set(core_od.origin_station_id) | set(core_od.destination_station_id))
    if len(nodes) != 2782: raise RuntimeError("core station universe is not 2,782 nodes")
    full_inventory = pq.ParquetFile(args.node_inventory).read().to_pandas().set_index("station_id")
    inventory = full_inventory.reindex(nodes).reset_index()
    if inventory.canonical_name.isna().any(): raise RuntimeError("station display metadata missing")
    base_identity = {"pipeline_version": PIPELINE_VERSION, "contract_sha256": sha256_file(args.contract),
                     "calendar_sha256": calendar_audit["source_sha256"], "od_policy_version": "od-inclusion-policy-v1",
                     "cleaned_partition_hashes_sha256": hash_value(cleaned_hashes),
                     "networkx_version": nx.__version__, "igraph_version": ig.__version__,
                     "station_order_sha256": hashlib.sha256("\n".join(nodes).encode()).hexdigest()}
    requested = [(d, h) for d in DAY_TYPES for h in range(24)]
    if args.gate_only: requested = [("weekday", args.weekday_gate_hour), ("holiday", args.holiday_gate_hour)]
    args.output_root.mkdir(parents=True, exist_ok=True)
    bucket_metrics = {}; receipts = []
    for day_type, hour in requested:
        edges = counter_to_edges(counters[(day_type, hour)])
        metrics, receipt = compute_bucket(day_type, hour, edges, nodes, args.output_root, base_identity,
                                          conservation["bucket_source_dates"][f"{day_type}-{hour:02d}"])
        bucket_metrics[(day_type, hour)] = metrics; receipts.append(receipt)
    if args.gate_only:
        result = {"pipeline_version": PIPELINE_VERSION, "status": "small_gate_passed", "calendar": calendar_audit,
                  "conservation": conservation, "gate_buckets": receipts, "full_execution": False,
                  "hierarchical_clustering_executed": False, "runtime_seconds": time.perf_counter() - started}
        write_json(args.gate_receipt, result); return result
    matrices = {}
    for day_type in DAY_TYPES:
        path, receipt = assemble_matrix(day_type, bucket_metrics, inventory, args.output_root)
        matrices[day_type] = {"path": str(path.relative_to(args.root)).replace("\\", "/"), **receipt}
    weekday_trips = sum(r["trip_count"] for r in receipts if r["day_type"] == "weekday")
    holiday_trips = sum(r["trip_count"] for r in receipts if r["day_type"] == "holiday")
    invocation_runtime = time.perf_counter() - started
    prior_initial_runtime = (previous_manifest or {}).get("initial_full_execution_runtime_seconds")
    result = {"pipeline_version": PIPELINE_VERSION, "status": "complete", "analysis_period": "2023-2024",
              "period_basis": contract["period_basis"], "calendar": calendar_audit,
              "source_identity": base_identity, "conservation": {**conservation, "weekday_trips": weekday_trips,
              "holiday_trips": holiday_trips, "bucket_sum_equals_expected": weekday_trips + holiday_trips == 91_138_763},
              "buckets": receipts, "matrices": matrices, "bucket_count": len(receipts),
              "exact_betweenness": True, "hierarchical_clustering_executed": False,
              "initial_full_execution_runtime_seconds": prior_initial_runtime or invocation_runtime,
              "latest_invocation_runtime_seconds": invocation_runtime,
              "validation_status": "passed"}
    write_json(args.manifest, result); return result


def main() -> None:
    root = Path(__file__).resolve().parents[1]; parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--contract", type=Path, default=root / "config/hourly_sna_feature_contract.yaml")
    parser.add_argument("--calendar", type=Path, default=root / "data/raw/2020_2025假日.fst")
    parser.add_argument("--rscript", type=Path, default=Path(r"C:\Program Files\R\R-4.5.2\bin\Rscript.exe"))
    parser.add_argument("--calendar-exporter", type=Path, default=root / "src/export_fst_calendar.R")
    parser.add_argument("--cleaned-root", type=Path, default=root / "data/processed/cleaned")
    parser.add_argument("--cleaning-manifest", type=Path, default=root / "notes/full-period-cleaning-manifest.json")
    parser.add_argument("--impact", type=Path, default=root / "notes/od-inclusion-impact.json")
    parser.add_argument("--current-metadata", type=Path, default=root / "data/raw/youbike_immediate_2026-09-13.json")
    parser.add_argument("--historical-metadata", type=Path, default=root / "data/raw/station_snapshot_2024-05-31.csv")
    parser.add_argument("--station-universe-evidence", type=Path, default=root / "notes/station-universe-classification.csv")
    parser.add_argument("--metadata-evidence", type=Path, default=root / "notes/station-metadata-evidence.json")
    parser.add_argument("--core-od", type=Path, default=root / "data/processed/od/aggregate/core_2023_2024/od.parquet")
    parser.add_argument("--node-inventory", type=Path, default=root / "data/processed/od/node_inventory.parquet")
    parser.add_argument("--output-root", type=Path, default=root / "data/processed/network/hourly_2023_2024")
    parser.add_argument("--calendar-audit", type=Path, default=root / "notes/holiday-calendar-audit.json")
    parser.add_argument("--gate-receipt", type=Path, default=root / "notes/hourly-sna-small-gate.json")
    parser.add_argument("--manifest", type=Path, default=root / "notes/hourly-sna-feature-manifest.json")
    parser.add_argument("--gate-only", action="store_true")
    parser.add_argument("--weekday-gate-hour", type=int, default=8)
    parser.add_argument("--holiday-gate-hour", type=int, default=14)
    args = parser.parse_args()
    result = run(args); print(json.dumps({"status": result["status"],
        "runtime_seconds": result.get("latest_invocation_runtime_seconds", result.get("runtime_seconds"))}))


if __name__ == "__main__": main()
