"""Validate OD-to-graph integrity and metric semantics without core SNA computation."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import networkx as nx
import pandas as pd
import pyarrow.parquet as pq

CONTRACT_VERSION = "network-metric-contract-v1"
METRICS = {"weighted_degree", "betweenness", "eigenvector", "pagerank", "clustering"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_contract(path: Path) -> dict[str, Any]:
    contract = json.loads(path.read_text(encoding="utf-8"))
    if contract.get("contract_version") != CONTRACT_VERSION:
        raise ValueError("unknown contract version")
    if set(contract.get("metrics", {})) != METRICS:
        raise ValueError("metric inventory mismatch")
    if contract.get("directed") is not True or contract.get("edge_flow_attribute") != "trip_count":
        raise ValueError("graph construction contract mismatch")
    allowed = {
        "weighted_degree": {"report_in_out_and_total"},
        "betweenness": {"directed"},
        "eigenvector": {"directed_left_predecessor_influence"},
        "pagerank": {"directed_origin_to_destination"},
        "clustering": {"undirected_simple_projection"},
    }
    for name, values in allowed.items():
        if contract["metrics"][name]["direction_mode"] not in values:
            raise ValueError(f"unknown direction mode for {name}")
    return contract


def graph_from_od(frame: pd.DataFrame) -> nx.DiGraph:
    required = {"origin_station_id", "destination_station_id", "trip_count"}
    if required.difference(frame.columns):
        raise ValueError("OD input missing required columns")
    if frame[list(required)].isna().any().any() or (frame["trip_count"] <= 0).any():
        raise ValueError("OD input contains null key or nonpositive flow")
    if frame.duplicated(["origin_station_id", "destination_station_id"]).any():
        raise ValueError("duplicate OD edge")
    graph = nx.DiGraph()
    graph.add_weighted_edges_from(
        frame[["origin_station_id", "destination_station_id", "trip_count"]].itertuples(index=False, name=None),
        weight="trip_count",
    )
    return graph


def without_self_loops(graph: nx.DiGraph) -> nx.DiGraph:
    result = graph.copy()
    result.remove_edges_from(nx.selfloop_edges(result))
    return result


def weighted_strength(graph: nx.DiGraph, node: str) -> dict[str, float]:
    incoming = float(graph.in_degree(node, weight="trip_count"))
    outgoing = float(graph.out_degree(node, weight="trip_count"))
    return {"in_strength": incoming, "out_strength": outgoing, "total_strength": incoming + outgoing}


def add_distance_transforms(graph: nx.DiGraph) -> nx.DiGraph:
    result = graph.copy()
    for _, _, data in result.edges(data=True):
        flow = float(data["trip_count"])
        if flow <= 0:
            raise ValueError("distance transform requires positive trip_count")
        data["inverse_flow_distance"] = 1.0 / flow
        data["inverse_log_flow_distance"] = 1.0 / math.log1p(flow)
    return result


def synthetic_graph() -> nx.DiGraph:
    graph = nx.DiGraph()
    graph.add_weighted_edges_from([
        ("A", "B", 1), ("A", "C", 10), ("C", "B", 10),
        ("B", "C", 2), ("B", "D", 3), ("C", "D", 1),
        ("D", "C", 1), ("A", "E", 1), ("D", "D", 5),
    ], weight="trip_count")
    return graph


def validate_synthetic() -> dict[str, Any]:
    graph = synthetic_graph()
    strength_d = weighted_strength(graph, "D")
    if strength_d != {"in_strength": 9.0, "out_strength": 6.0, "total_strength": 15.0}:
        raise AssertionError("weighted strength/self-loop behavior changed")
    metric_graph = without_self_loops(graph)
    transformed = add_distance_transforms(metric_graph)
    unweighted_path = nx.shortest_path(metric_graph, "A", "B")
    inverse_path = nx.shortest_path(transformed, "A", "B", weight="inverse_flow_distance")
    if unweighted_path != ["A", "B"] or inverse_path != ["A", "C", "B"]:
        raise AssertionError("betweenness distance transform semantics changed")
    bet_unweighted = nx.betweenness_centrality(metric_graph, normalized=True, weight=None, endpoints=False)
    bet_inverse = nx.betweenness_centrality(transformed, normalized=True,
                                             weight="inverse_flow_distance", endpoints=False)
    eigen_left = nx.eigenvector_centrality(metric_graph, max_iter=1000, tol=1e-9, weight=None)
    eigen_right = nx.eigenvector_centrality(metric_graph.reverse(copy=True), max_iter=1000, tol=1e-9, weight=None)
    if eigen_left == eigen_right:
        raise AssertionError("directed eigenvector left/right test is not discriminating")
    page_weighted = nx.pagerank(graph, alpha=0.85, weight="trip_count", max_iter=1000, tol=1e-9)
    page_unweighted = nx.pagerank(graph, alpha=0.85, weight=None, max_iter=1000, tol=1e-9)
    if abs(sum(page_weighted.values()) - 1.0) > 1e-9 or page_weighted == page_unweighted:
        raise AssertionError("PageRank weight/normalization behavior changed")
    undirected = nx.Graph()
    undirected.add_edges_from((u, v) for u, v in metric_graph.edges())
    clustering = nx.clustering(undirected, weight=None)
    triangle = nx.Graph([("x", "y"), ("y", "z"), ("z", "x"), ("x", "tail")])
    triangle_values = nx.clustering(triangle, weight=None)
    if triangle_values["y"] != 1.0 or abs(triangle_values["x"] - 1 / 3) > 1e-12:
        raise AssertionError("undirected local clustering formula changed")
    return {
        "networkx_version": nx.__version__, "nodes": graph.number_of_nodes(),
        "edges": graph.number_of_edges(), "self_loop_edges": nx.number_of_selfloops(graph),
        "weighted_strength_node_D": strength_d,
        "shortest_path_unweighted_A_to_B": unweighted_path,
        "shortest_path_inverse_flow_A_to_B": inverse_path,
        "betweenness_unweighted": bet_unweighted, "betweenness_inverse_flow": bet_inverse,
        "eigenvector_left_predecessor": eigen_left, "eigenvector_right_via_reverse": eigen_right,
        "pagerank_weighted": page_weighted, "pagerank_unweighted": page_unweighted,
        "pagerank_weighted_sum": sum(page_weighted.values()),
        "clustering_undirected_projection": clustering,
        "clustering_formula_probe": triangle_values,
        "validation_status": "passed",
    }


def validate_core(od_path: Path, manifest_path: Path) -> dict[str, Any]:
    frame = pq.ParquetFile(od_path).read().to_pandas()
    graph = graph_from_od(frame)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = next(row for row in manifest["aggregates"] if row["period"] == "core_2023_2024")
    observed = {
        "node_count": graph.number_of_nodes(), "edge_count": graph.number_of_edges(),
        "weight_sum": int(graph.size(weight="trip_count")),
        "self_loop_edges": nx.number_of_selfloops(graph),
        "self_loop_trips": int(sum(data["trip_count"] for u, v, data in graph.edges(data=True) if u == v)),
        "duplicate_od_edges": int(frame.duplicated(["origin_station_id", "destination_station_id"]).sum()),
        "null_station_ids": int(frame[["origin_station_id", "destination_station_id"]].isna().any(axis=1).sum()),
        "directed": graph.is_directed(), "multigraph": graph.is_multigraph(),
    }
    checks = {
        "node_count": observed["node_count"] == expected["node_count"] == 2782,
        "edge_count": observed["edge_count"] == expected["edge_count"] == 1125519,
        "weight_sum": observed["weight_sum"] == expected["total_trip_count"] == 91138763,
        "self_loop_edges": observed["self_loop_edges"] == expected["self_loop_edges"] == 1504,
        "self_loop_trips": observed["self_loop_trips"] == expected["self_loop_trips"] == 6023568,
        "unique_edges": observed["duplicate_od_edges"] == 0,
        "station_ids_present": observed["null_station_ids"] == 0,
        "directed_simple_graph": observed["directed"] and not observed["multigraph"],
    }
    if not all(checks.values()):
        raise RuntimeError(f"core graph integrity failed: {checks}")
    return {"source_od_sha256": sha256_file(od_path), "observed": observed,
            "checks": checks, "validation_status": "passed",
            "formal_core_metrics_computed": False}


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=root / "config/network_metric_contract.yaml")
    parser.add_argument("--core-od", type=Path, default=root / "data/processed/od/aggregate/core_2023_2024/od.parquet")
    parser.add_argument("--od-manifest", type=Path, default=root / "notes/od-aggregation-manifest.json")
    parser.add_argument("--output", type=Path, default=root / "notes/network-construction-validation.json")
    args = parser.parse_args()
    contract = load_contract(args.contract)
    output = {"contract_version": contract["contract_version"],
              "contract_sha256": sha256_file(args.contract),
              "core_graph_integrity": validate_core(args.core_od, args.od_manifest),
              "synthetic_metric_validation": validate_synthetic(),
              "scope_guard": {"core_period": "2023/01-2024/12",
                              "full_core_centrality_computed": False}}
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "passed", "core": output["core_graph_integrity"]["observed"]}))


if __name__ == "__main__":
    main()
