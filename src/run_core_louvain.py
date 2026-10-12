"""Execute Phase 6.1 core Louvain and finalized sensitivity variants."""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import math
import os
from pathlib import Path
import time
from typing import Any

import networkx as nx
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score

from validate_louvain_contract import (deterministic_relabel, load_contract, project_od,
                                       sha256_file, write_json)

PIPELINE_VERSION = "core-louvain-v1"


def peak_working_set_bytes() -> int | None:
    if os.name != "nt":
        return None
    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                    ("PrivateUsage", ctypes.c_size_t)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    api = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    api.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    api.GetProcessMemoryInfo.restype = wintypes.BOOL
    counters = Counters(); counters.cb = ctypes.sizeof(counters)
    if api.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        return int(counters.PeakWorkingSetSize)
    return None


def graph_fingerprint(graph: nx.Graph) -> str:
    digest = hashlib.sha256()
    for node in sorted(map(str, graph.nodes())):
        digest.update(f"N\t{node}\n".encode())
    edges = sorted((min(str(u), str(v)), max(str(u), str(v)), int(data["trip_count"]))
                   for u, v, data in graph.edges(data=True))
    for u, v, weight in edges:
        digest.update(f"E\t{u}\t{v}\t{weight}\n".encode())
    return digest.hexdigest()


def partition_fingerprint(labels: dict[str, int]) -> str:
    payload = "".join(f"{node}\t{labels[node]}\n" for node in sorted(labels))
    return hashlib.sha256(payload.encode()).hexdigest()


def modularity_contributions(graph: nx.Graph, communities: list[set[str]],
                             resolution: float) -> list[dict[str, Any]]:
    total_weight = float(graph.size(weight="trip_count"))
    if total_weight <= 0:
        raise ValueError("modularity requires positive total graph weight")
    labels = deterministic_relabel(communities)
    output = []
    for community in communities:
        community_id = labels[min(community)]
        internal_weight = float(graph.subgraph(community).size(weight="trip_count"))
        total_strength = float(sum(graph.degree(node, weight="trip_count") for node in community))
        contribution = internal_weight / total_weight - resolution * (total_strength / (2 * total_weight)) ** 2
        output.append({"community_id": community_id, "internal_projected_weight": int(internal_weight),
                       "projected_total_strength": int(total_strength),
                       "modularity_contribution": contribution})
    return sorted(output, key=lambda item: item["community_id"])


def execute_louvain(graph: nx.Graph, contract: dict[str, Any], *, seed: int,
                    resolution: float) -> dict[str, Any]:
    started = time.perf_counter()
    communities = nx.community.louvain_communities(
        graph, weight="trip_count", resolution=resolution,
        threshold=float(contract["algorithm"]["threshold"]),
        max_level=contract["algorithm"]["max_level"], seed=seed)
    runtime = time.perf_counter() - started
    communities = [set(map(str, community)) for community in communities]
    labels = deterministic_relabel(communities)
    modularity = float(nx.community.modularity(graph, communities, weight="trip_count", resolution=resolution))
    contributions = modularity_contributions(graph, communities, resolution)
    contribution_sum = float(sum(item["modularity_contribution"] for item in contributions))
    if not math.isclose(modularity, contribution_sum, abs_tol=1e-12):
        raise RuntimeError("manual modularity contribution sum differs from NetworkX")
    if len(labels) != graph.number_of_nodes() or set(labels) != set(map(str, graph.nodes())):
        raise RuntimeError("partition does not assign every graph node exactly once")
    return {"communities": communities, "labels": labels, "modularity": modularity,
            "contribution_sum": contribution_sum, "contributions": contributions,
            "community_count": len(communities), "runtime_seconds": runtime,
            "partition_fingerprint": partition_fingerprint(labels)}


def compare_partition(primary_labels: dict[str, int], variant_labels: dict[str, int]) -> tuple[float, float]:
    nodes = sorted(primary_labels)
    if set(nodes) != set(variant_labels):
        raise ValueError("partition node sets differ")
    primary = [primary_labels[node] for node in nodes]
    variant = [variant_labels[node] for node in nodes]
    return (float(adjusted_rand_score(primary, variant)),
            float(normalized_mutual_info_score(primary, variant)))


def atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp.parquet")
    pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), temporary, compression="zstd")
    os.replace(temporary, path)


def top_station(frame: pd.DataFrame, metric: str) -> tuple[str, str]:
    row = frame.sort_values([metric, "station_id"], ascending=[False, True], kind="mergesort").iloc[0]
    return str(row.station_id), str(row.station_name)


def make_community_summary(stations: pd.DataFrame, od: pd.DataFrame, projected: nx.Graph,
                           primary: dict[str, Any]) -> pd.DataFrame:
    labels = primary["labels"]
    od = od.copy()
    od["origin_community"] = od.origin_station_id.map(labels)
    od["destination_community"] = od.destination_station_id.map(labels)
    contribution_map = {item["community_id"]: item for item in primary["contributions"]}
    rows = []
    for community_id, group in stations.groupby("community_id", sort=True):
        internal = od[(od.origin_community == community_id) & (od.destination_community == community_id)]
        outgoing = od[(od.origin_community == community_id) & (od.destination_community != community_id)]
        incoming = od[(od.destination_community == community_id) & (od.origin_community != community_id)]
        top_strength_id, top_strength_name = top_station(group, "total_strength")
        top_pagerank_id, top_pagerank_name = top_station(group, "pagerank_primary")
        top_between_id, top_between_name = top_station(group, "betweenness_primary")
        city_counts = group.city.value_counts()
        dominant_city = sorted(city_counts[city_counts == city_counts.max()].index.astype(str))[0]
        contribution = contribution_map[int(community_id)]
        rows.append({
            "community_id": int(community_id), "node_count": len(group),
            "dominant_city": dominant_city,
            "total_node_strength": int(group.total_strength.sum()),
            "internal_trip_weight": int(internal.trip_count.sum()),
            "external_trip_weight": int(outgoing.trip_count.sum()),
            "boundary_trip_weight": int(outgoing.trip_count.sum() + incoming.trip_count.sum()),
            "internal_edge_count": len(internal), "external_edge_count": len(outgoing),
            "top_station_by_total_strength_id": top_strength_id,
            "top_station_by_total_strength": top_strength_name,
            "top_station_by_pagerank_id": top_pagerank_id,
            "top_station_by_pagerank": top_pagerank_name,
            "top_station_by_betweenness_id": top_between_id,
            "top_station_by_betweenness": top_between_name,
            **contribution,
        })
    return pd.DataFrame(rows).sort_values("community_id").reset_index(drop=True)


def size_summary(labels: dict[str, int]) -> dict[str, Any]:
    sizes = pd.Series(labels).value_counts().sort_index()
    return {"community_count": len(sizes), "min": int(sizes.min()),
            "median": float(sizes.median()), "mean": float(sizes.mean()),
            "max": int(sizes.max()), "singleton_count": int((sizes == 1).sum()),
            "node_counts": [{"community_id": int(key), "node_count": int(value)}
                            for key, value in sizes.items()]}


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    contract = load_contract(args.contract)
    od = pq.ParquetFile(args.core_od).read().to_pandas()
    metrics = pq.ParquetFile(args.node_metrics).read().to_pandas()
    primary_graph = project_od(od, mode="sum", remove_self_loops=True)
    expected = {"nodes": 2782, "edges": 748591, "weight": 85115195, "loops": 0}
    observed = {"nodes": primary_graph.number_of_nodes(), "edges": primary_graph.number_of_edges(),
                "weight": int(primary_graph.size(weight="trip_count")),
                "loops": nx.number_of_selfloops(primary_graph)}
    loop_mask = od.origin_station_id == od.destination_station_id
    loop_edges, loop_weight = int(loop_mask.sum()), int(od.loc[loop_mask, "trip_count"].sum())
    if observed != expected or loop_edges != 1504 or loop_weight != 6023568:
        raise RuntimeError(f"primary graph QA mismatch: observed={observed}, loops={loop_edges}/{loop_weight}")
    if observed["weight"] + loop_weight != int(od.trip_count.sum()):
        raise RuntimeError("projection weight conservation failed")

    primary = execute_louvain(primary_graph, contract, seed=42, resolution=1.0)
    primary_repeat = execute_louvain(primary_graph, contract, seed=42, resolution=1.0)
    if (primary["partition_fingerprint"] != primary_repeat["partition_fingerprint"] or
            primary["community_count"] != primary_repeat["community_count"] or
            not math.isclose(primary["modularity"], primary_repeat["modularity"], abs_tol=1e-15)):
        raise RuntimeError("primary fixed-seed reproducibility failed")

    primary_labels = primary["labels"]
    variants: list[dict[str, Any]] = []

    def record(name: str, graph: nx.Graph, result: dict[str, Any], projection: str,
               self_loop_mode: str, resolution: float, seed: int, weighted: bool) -> None:
        ari, nmi = compare_partition(primary_labels, result["labels"])
        variants.append({"variant": name, "projection": projection, "self_loop_mode": self_loop_mode,
                         "resolution": resolution, "seed": seed, "weighted": weighted,
                         "node_count": graph.number_of_nodes(), "edge_count": graph.number_of_edges(),
                         "total_weight": int(graph.size(weight="trip_count")),
                         "community_count": result["community_count"], "modularity": result["modularity"],
                         "ari_vs_primary": ari, "nmi_vs_primary": nmi,
                         "runtime_seconds": result["runtime_seconds"],
                         "partition_fingerprint": result["partition_fingerprint"]})

    record("primary_seed_42", primary_graph, primary, "sum", "removed", 1.0, 42, True)
    for seed in [7, 19, 73]:
        result = execute_louvain(primary_graph, contract, seed=seed, resolution=1.0)
        record(f"seed_{seed}", primary_graph, result, "sum", "removed", 1.0, seed, True)
    for mode in ["max", "unweighted"]:
        graph = project_od(od, mode=mode, remove_self_loops=True)
        result = execute_louvain(graph, contract, seed=42, resolution=1.0)
        record(f"projection_{mode}", graph, result, mode, "removed", 1.0, 42, mode != "unweighted")
    retained_graph = project_od(od, mode="sum", remove_self_loops=False)
    retained = execute_louvain(retained_graph, contract, seed=42, resolution=1.0)
    record("self_loop_retain", retained_graph, retained, "sum", "retained", 1.0, 42, True)
    for resolution in [0.5, 1.5]:
        result = execute_louvain(primary_graph, contract, seed=42, resolution=resolution)
        record(f"resolution_{str(resolution).replace('.', '_')}", primary_graph, result,
               "sum", "removed", resolution, 42, True)

    station_columns = ["station_id", "station_name", "city", "in_strength", "out_strength",
                       "total_strength", "pagerank_primary", "betweenness_primary"]
    stations = metrics[station_columns].copy()
    stations["community_id"] = stations.station_id.map(primary_labels)
    if len(stations) != 2782 or stations.station_id.duplicated().any() or stations.community_id.isna().any():
        raise RuntimeError("station assignment validation failed")
    sizes = pd.Series(primary_labels).value_counts()
    stations["community_id"] = stations.community_id.astype("int64")
    stations["community_size"] = stations.community_id.map(sizes).astype("int64")
    stations = stations[["station_id", "station_name", "city", "community_id", "community_size",
                         "in_strength", "out_strength", "total_strength", "pagerank_primary",
                         "betweenness_primary"]].sort_values("station_id").reset_index(drop=True)
    community_summary = make_community_summary(stations, od, primary_graph, primary)

    atomic_parquet(stations, args.partition_output)
    atomic_parquet(community_summary, args.community_output)
    community_summary.to_csv(args.community_csv, index=False, encoding="utf-8-sig")
    sensitivity = {"contract_version": contract["contract_version"],
                   "comparison_metrics": ["adjusted_rand_index", "normalized_mutual_information"],
                   "variants": variants}
    write_json(args.sensitivity_output, sensitivity)
    primary_summary = {
        "contract_version": contract["contract_version"], "seed": 42, "resolution": 1.0,
        "projection": "sum", "self_loop_mode": "removed",
        "community_count": primary["community_count"], "modularity": primary["modularity"],
        "contribution_sum": primary["contribution_sum"],
        "modularity_tolerance": 1e-12, "community_sizes": size_summary(primary_labels),
        "partition_fingerprint": primary["partition_fingerprint"],
        "fixed_seed_repeat_fingerprint": primary_repeat["partition_fingerprint"],
        "fixed_seed_reproducible": True,
        "report_comparison": {
            "report_community_count_approx": 11,
            "reconstruction_community_count": primary["community_count"],
            "community_count_classification": "materially_different",
            "report_modularity_contribution_sum": 0.66574,
            "reconstruction_modularity": primary["modularity"],
            "absolute_modularity_difference": abs(primary["modularity"] - 0.66574),
            "modularity_classification": "broadly_similar",
            "implementation_equivalence": "cannot_verify",
        },
        "communities": community_summary.to_dict(orient="records"),
    }
    write_json(args.primary_summary, primary_summary)

    receipt = {
        "pipeline_version": PIPELINE_VERSION, "contract_version": contract["contract_version"],
        "contract_sha256": sha256_file(args.contract), "networkx_version": nx.__version__,
        "core_od_sha256": sha256_file(args.core_od), "node_metrics_sha256": sha256_file(args.node_metrics),
        "projected_graph_fingerprint": graph_fingerprint(primary_graph),
        "projection_mode": "sum", "self_loop_mode": "removed", "resolution": 1.0,
        "seed": 42, "threshold": float(contract["algorithm"]["threshold"]),
        "node_count": observed["nodes"], "edge_count": observed["edges"],
        "total_projected_weight": observed["weight"], "removed_self_loop_edges": loop_edges,
        "removed_self_loop_weight": loop_weight, "community_count": primary["community_count"],
        "modularity": primary["modularity"], "contribution_sum": primary["contribution_sum"],
        "primary_runtime_seconds": primary["runtime_seconds"],
        "primary_repeat_runtime_seconds": primary_repeat["runtime_seconds"],
        "total_runtime_seconds": time.perf_counter() - started,
        "peak_working_set_bytes": peak_working_set_bytes(),
        "partition_output_sha256": sha256_file(args.partition_output),
        "community_output_sha256": sha256_file(args.community_output),
        "partition_output_bytes": args.partition_output.stat().st_size,
        "community_output_bytes": args.community_output.stat().st_size,
        "partition_fingerprint": primary["partition_fingerprint"],
        "fixed_seed_reproducible": True,
        "validation": {"projection_qa": True, "weight_conservation": True,
                       "all_nodes_assigned_once": True, "community_ids_contiguous":
                       sorted(stations.community_id.unique()) == list(range(1, primary["community_count"] + 1)),
                       "modularity_decomposition": math.isclose(primary["modularity"], primary["contribution_sum"], abs_tol=1e-12),
                       "fixed_seed_partition_reproduced": True, "no_kmeans_or_hierarchical": True},
        "validation_status": "passed",
    }
    if not all(receipt["validation"].values()):
        raise RuntimeError(f"receipt validation failed: {receipt['validation']}")
    write_json(args.receipt, receipt)
    return receipt


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=root / "config/louvain_contract.yaml")
    parser.add_argument("--core-od", type=Path, default=root / "data/processed/od/aggregate/core_2023_2024/od.parquet")
    parser.add_argument("--node-metrics", type=Path, default=root / "data/processed/network/core_2023_2024/node_metrics.parquet")
    parser.add_argument("--partition-output", type=Path, default=root / "data/processed/network/core_2023_2024/louvain_partition.parquet")
    parser.add_argument("--community-output", type=Path, default=root / "data/processed/network/core_2023_2024/louvain_community_summary.parquet")
    parser.add_argument("--primary-summary", type=Path, default=root / "notes/louvain-primary-summary.json")
    parser.add_argument("--sensitivity-output", type=Path, default=root / "notes/louvain-sensitivity-summary.json")
    parser.add_argument("--community-csv", type=Path, default=root / "notes/louvain-community-summary.csv")
    parser.add_argument("--receipt", type=Path, default=root / "notes/louvain-run-receipt.json")
    result = run(parser.parse_args())
    print(json.dumps({"status": result["validation_status"], "community_count": result["community_count"],
                      "modularity": result["modularity"]}))


if __name__ == "__main__":
    main()
