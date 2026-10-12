"""Execute Phase 5.0 core SNA metrics from the finalized network contract."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import time
from typing import Any, Callable

import networkx as nx
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from validate_network_contract import (add_distance_transforms, graph_from_od, load_contract,
                                       sha256_file, without_self_loops)

PIPELINE_VERSION = "core-sna-metrics-v1"
PRIMARY_RANKINGS = {
    "in_strength": "in_strength", "out_strength": "out_strength",
    "total_strength": "total_strength", "betweenness_primary": "betweenness_primary",
    "eigenvector_primary": "eigenvector_primary", "pagerank_primary": "pagerank_primary",
    "clustering_primary": "clustering_primary",
}
SENSITIVITY_PAIRS = [
    ("betweenness_primary", "betweenness_inverse_flow"),
    ("betweenness_primary", "betweenness_log_inverse_flow"),
    ("eigenvector_primary", "eigenvector_weighted"),
    ("eigenvector_primary", "eigenvector_reverse"),
    ("pagerank_primary", "pagerank_unweighted"),
    ("clustering_primary", "clustering_directed"),
    ("clustering_primary", "clustering_weighted"),
]


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _memory_peak() -> int | None:
    if os.name != "nt": return None
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
        kernel = ctypes.WinDLL("kernel32", use_last_error=True); api = ctypes.WinDLL("psapi", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        api.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        api.GetProcessMemoryInfo.restype = wintypes.BOOL
        counters = Counters(); counters.cb = ctypes.sizeof(counters)
        if api.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            return int(counters.PeakWorkingSetSize)
    except (AttributeError, OSError): pass
    return None


def _series_path(checkpoint: Path, name: str) -> Path:
    return checkpoint / f"{name}.parquet"


def compute_or_load(name: str, nodes: list[str], checkpoint: Path,
                    identity: dict[str, str], compute: Callable[[], dict[str, float]],
                    timings: dict[str, float]) -> pd.Series:
    path = _series_path(checkpoint, name); meta_path = checkpoint / f"{name}.json"
    if path.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("identity") == identity and meta.get("output_sha256") == sha256_file(path):
            frame = pq.ParquetFile(path).read().to_pandas()
            series = frame.set_index("station_id")[name].reindex(nodes)
            if len(series) == len(nodes) and series.notna().all():
                timings[name] = meta["runtime_seconds"]
                return series
    started = time.perf_counter(); values = compute(); runtime = time.perf_counter() - started
    series = pd.Series(values, name=name, dtype=float).reindex(nodes)
    if series.isna().any() or not all(math.isfinite(float(v)) for v in series):
        raise RuntimeError(f"{name} contains missing or nonfinite values")
    checkpoint.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pandas(series.rename_axis("station_id").reset_index(), preserve_index=False), path,
                   compression="zstd")
    timings[name] = runtime
    _write_json(meta_path, {"identity": identity, "runtime_seconds": runtime,
                            "output_sha256": sha256_file(path), "status": "complete"})
    return series


def deterministic_rank(metrics: pd.DataFrame, column: str, top_n: int = 20) -> pd.DataFrame:
    columns = ["station_id", "station_name", "city", column]
    ranked = metrics[columns].sort_values([column, "station_id"], ascending=[False, True], kind="mergesort").head(top_n)
    ranked = ranked.copy().rename(columns={column: "value"})
    ranked.insert(0, "rank", range(1, len(ranked) + 1)); ranked.insert(1, "metric", column)
    return ranked


def sensitivity_summary(metrics: pd.DataFrame) -> list[dict[str, Any]]:
    output = []
    for primary, variant in SENSITIVITY_PAIRS:
        p = metrics.set_index("station_id")[primary]; v = metrics.set_index("station_id")[variant]
        p_rank = p.rank(method="average", ascending=False); v_rank = v.rank(method="average", ascending=False)
        p_top = set(p.sort_values(ascending=False, kind="mergesort").head(20).index)
        v_top = set(v.sort_values(ascending=False, kind="mergesort").head(20).index)
        output.append({"primary": primary, "variant": variant,
                       "spearman_rank_correlation": float(p_rank.corr(v_rank, method="pearson")),
                       "top20_overlap_count": len(p_top & v_top),
                       "top20_overlap_fraction": len(p_top & v_top) / 20})
    return output


def validate_metrics(metrics: pd.DataFrame, weight_sum: int) -> dict[str, Any]:
    numeric = metrics.select_dtypes(include="number")
    checks = {
        "node_count_2782": len(metrics) == 2782,
        "station_id_unique": metrics.station_id.is_unique,
        "no_nan": not numeric.isna().any().any(),
        "all_finite": bool(numeric.map(lambda x: math.isfinite(float(x))).all().all()),
        "in_strength_conservation": int(metrics.in_strength.sum()) == weight_sum,
        "out_strength_conservation": int(metrics.out_strength.sum()) == weight_sum,
        "total_strength_conservation": int(metrics.total_strength.sum()) == 2 * weight_sum,
        "pagerank_primary_sum": abs(float(metrics.pagerank_primary.sum()) - 1.0) <= 1e-8,
        "pagerank_unweighted_sum": abs(float(metrics.pagerank_unweighted.sum()) - 1.0) <= 1e-8,
        "eigenvector_primary_norm": abs(float((metrics.eigenvector_primary ** 2).sum()) - 1.0) <= 1e-6,
        "eigenvector_weighted_norm": abs(float((metrics.eigenvector_weighted ** 2).sum()) - 1.0) <= 1e-6,
        "eigenvector_reverse_norm": abs(float((metrics.eigenvector_reverse ** 2).sum()) - 1.0) <= 1e-6,
    }
    for column in [c for c in metrics if c.startswith("betweenness_") or c.startswith("clustering_")]:
        checks[f"{column}_range"] = bool(metrics[column].between(0, 1).all())
    for column in ["in_strength", "out_strength", "total_strength"]:
        checks[f"{column}_nonnegative_integer"] = bool((metrics[column] >= 0).all() and
                                                        (metrics[column] % 1 == 0).all())
    if not all(checks.values()): raise RuntimeError(f"metric validation failed: {checks}")
    return checks


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter(); contract = load_contract(args.contract)
    od_hash = sha256_file(args.core_od); contract_hash = sha256_file(args.contract)
    identity = {"contract_version": contract["contract_version"], "contract_sha256": contract_hash,
                "core_od_sha256": od_hash, "networkx_version": nx.__version__}
    od = pq.ParquetFile(args.core_od).read().to_pandas()
    graph = graph_from_od(od); nodes = sorted(graph.nodes())
    metric_graph = without_self_loops(graph); transformed = add_distance_transforms(metric_graph)
    inventory = pq.ParquetFile(args.node_inventory).read().to_pandas().set_index("station_id").reindex(nodes)
    metrics = inventory[["canonical_name", "city", "observed_as_origin", "observed_as_destination"]].reset_index()
    metrics = metrics.rename(columns={"canonical_name": "station_name"})
    metrics["in_strength"] = metrics.station_id.map(dict(graph.in_degree(weight="trip_count"))).astype("int64")
    metrics["out_strength"] = metrics.station_id.map(dict(graph.out_degree(weight="trip_count"))).astype("int64")
    metrics["total_strength"] = metrics.in_strength + metrics.out_strength
    timings: dict[str, float] = {}
    checkpoint = args.output.parent / ".phase5-checkpoints"
    specs: list[tuple[str, Callable[[], dict[str, float]]]] = [
        ("betweenness_primary", lambda: nx.betweenness_centrality(metric_graph, normalized=True, weight=None, endpoints=False)),
        ("betweenness_inverse_flow", lambda: nx.betweenness_centrality(transformed, normalized=True, weight="inverse_flow_distance", endpoints=False)),
        ("betweenness_log_inverse_flow", lambda: nx.betweenness_centrality(transformed, normalized=True, weight="inverse_log_flow_distance", endpoints=False)),
        ("eigenvector_primary", lambda: nx.eigenvector_centrality(metric_graph, max_iter=1000, tol=1e-9, weight=None)),
        ("eigenvector_weighted", lambda: nx.eigenvector_centrality(metric_graph, max_iter=1000, tol=1e-9, weight="trip_count")),
        ("eigenvector_reverse", lambda: nx.eigenvector_centrality(metric_graph.reverse(copy=True), max_iter=1000, tol=1e-9, weight=None)),
        ("pagerank_primary", lambda: nx.pagerank(graph, alpha=0.85, weight="trip_count", max_iter=1000, tol=1e-9)),
        ("pagerank_unweighted", lambda: nx.pagerank(graph, alpha=0.85, weight=None, max_iter=1000, tol=1e-9)),
    ]
    for name, function in specs:
        metrics[name] = metrics.station_id.map(compute_or_load(name, nodes, checkpoint, identity, function, timings))
    undirected = nx.Graph(); undirected.add_nodes_from(nodes); undirected.add_edges_from(metric_graph.edges())
    weighted_undirected = nx.Graph(); weighted_undirected.add_nodes_from(nodes)
    for u, v, data in metric_graph.edges(data=True):
        flow = data["trip_count"]
        if weighted_undirected.has_edge(u, v): weighted_undirected[u][v]["trip_count"] += flow
        else: weighted_undirected.add_edge(u, v, trip_count=flow)
    cluster_specs = [
        ("clustering_primary", lambda: nx.clustering(undirected, weight=None)),
        ("clustering_directed", lambda: nx.clustering(metric_graph, weight=None)),
        ("clustering_weighted", lambda: nx.clustering(weighted_undirected, weight="trip_count")),
    ]
    for name, function in cluster_specs:
        metrics[name] = metrics.station_id.map(compute_or_load(name, nodes, checkpoint, identity, function, timings))
    checks = validate_metrics(metrics, 91138763)
    rankings = pd.concat([deterministic_rank(metrics, col) for col in PRIMARY_RANKINGS], ignore_index=True)
    comparisons = sensitivity_summary(metrics)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.output.with_suffix(".tmp.parquet")
    pq.write_table(pa.Table.from_pandas(metrics, preserve_index=False), tmp, compression="zstd")
    os.replace(tmp, args.output)
    rankings.to_csv(args.rankings, index=False, encoding="utf-8-sig")
    _write_json(args.sensitivity, {"contract_version": contract["contract_version"], "comparisons": comparisons})
    metric_parameters = {
        "strength": {"weight": "trip_count", "normalization": "none", "self_loops": "included"},
        "betweenness_primary": {"directed": True, "weight": None, "normalized": True,
                                    "endpoints": False, "self_loops": "excluded", "exact": True},
        "betweenness_inverse_flow": {"distance": "1/trip_count", "normalized": True,
                                        "endpoints": False, "self_loops": "excluded", "exact": True},
        "betweenness_log_inverse_flow": {"distance": "1/log1p(trip_count)", "normalized": True,
                                            "endpoints": False, "self_loops": "excluded", "exact": True},
        "eigenvector_primary": {"directed_semantics": "left_predecessor", "weight": None,
                                  "max_iter": 1000, "tol": 1e-9, "self_loops": "excluded"},
        "eigenvector_weighted": {"directed_semantics": "left_predecessor", "weight": "trip_count",
                                   "max_iter": 1000, "tol": 1e-9, "self_loops": "excluded"},
        "eigenvector_reverse": {"directed_semantics": "right_via_reversed_graph", "weight": None,
                                  "max_iter": 1000, "tol": 1e-9, "self_loops": "excluded"},
        "pagerank_primary": {"weight": "trip_count", "alpha": 0.85, "personalization": "uniform",
                               "dangling": "uniform", "max_iter": 1000, "tol": 1e-9,
                               "self_loops": "included"},
        "pagerank_unweighted": {"weight": None, "alpha": 0.85, "personalization": "uniform",
                                  "dangling": "uniform", "max_iter": 1000, "tol": 1e-9,
                                  "self_loops": "included"},
        "clustering_primary": {"graph": "undirected_simple_projection", "weight": None,
                                  "self_loops": "excluded"},
        "clustering_directed": {"graph": "directed", "weight": None, "self_loops": "excluded"},
        "clustering_weighted": {"graph": "undirected_reciprocal_sum", "weight": "trip_count",
                                   "self_loops": "excluded"},
    }
    invocation_runtime = time.perf_counter() - started
    receipt = {"pipeline_version": PIPELINE_VERSION, **identity, "node_count": graph.number_of_nodes(),
               "edge_count": graph.number_of_edges(), "weight_sum": int(graph.size(weight="trip_count")),
               "self_loop_edges": nx.number_of_selfloops(graph), "per_metric_runtime_seconds": timings,
               "per_metric_parameters": metric_parameters,
               "cumulative_metric_runtime_seconds": sum(timings.values()),
               "finalization_invocation_runtime_seconds": invocation_runtime,
               "peak_working_set_bytes": _memory_peak(),
               "output_sha256": sha256_file(args.output), "output_bytes": args.output.stat().st_size,
               "numeric_tolerances": {"pagerank_sum": 1e-8, "eigenvector_squared_norm": 1e-6},
               "validation": checks, "convergence_status": "all_converged",
               "validation_status": "passed", "formal_metrics_complete": True}
    _write_json(args.receipt, receipt)
    return receipt


def main() -> None:
    root = Path(__file__).resolve().parents[1]; parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=root / "config/network_metric_contract.yaml")
    parser.add_argument("--core-od", type=Path, default=root / "data/processed/od/aggregate/core_2023_2024/od.parquet")
    parser.add_argument("--node-inventory", type=Path, default=root / "data/processed/od/node_inventory.parquet")
    parser.add_argument("--output", type=Path, default=root / "data/processed/network/core_2023_2024/node_metrics.parquet")
    parser.add_argument("--rankings", type=Path, default=root / "notes/sna-primary-rankings.csv")
    parser.add_argument("--sensitivity", type=Path, default=root / "notes/sna-sensitivity-summary.json")
    parser.add_argument("--receipt", type=Path, default=root / "notes/sna-metrics-receipt.json")
    receipt = run(parser.parse_args()); print(json.dumps({"status": receipt["validation_status"], "nodes": receipt["node_count"]}))


if __name__ == "__main__": main()
