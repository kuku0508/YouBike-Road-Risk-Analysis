"""Validate the Phase 6.0 Louvain reconstruction contract without core Louvain."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

import networkx as nx
import pandas as pd
import pyarrow.parquet as pq

CONTRACT_VERSION = "louvain-reconstruction-contract-v1"
PROJECTION_MODES = {"sum", "max", "unweighted"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_contract(path: Path) -> dict[str, Any]:
    contract = json.loads(path.read_text(encoding="utf-8"))
    if contract.get("contract_version") != CONTRACT_VERSION:
        raise ValueError("unknown Louvain contract version")
    target = contract.get("target_graph", {})
    if target.get("projection_mode") not in PROJECTION_MODES:
        raise ValueError("unknown projection mode")
    if target.get("self_loop_mode") not in {"remove_before_projection", "retain"}:
        raise ValueError("unknown self-loop mode")
    required_target = {
        "type": "undirected_simple_weighted",
        "projection_mode": "sum",
        "weight": "trip_count",
        "self_loop_mode": "remove_before_projection",
        "isolated_node_policy": "retain_as_singleton_community",
    }
    for key, value in required_target.items():
        if target.get(key) != value:
            raise ValueError(f"primary target {key} mismatch")
    algorithm = contract.get("algorithm", {})
    expected = {
        "library": "networkx",
        "library_version": nx.__version__,
        "function": "networkx.algorithms.community.louvain_communities",
        "backend": "networkx_builtin",
    }
    for key, value in expected.items():
        if algorithm.get(key) != value:
            raise ValueError(f"algorithm {key} mismatch")
    if contract.get("phase_6_0_guard", {}).get("full_core_louvain_allowed") is not False:
        raise ValueError("Phase 6.0 must forbid full-core Louvain")
    if float(algorithm.get("resolution", -1)) <= 0 or algorithm.get("seed") is None:
        raise ValueError("resolution must be positive and seed must be fixed")
    modularity = contract.get("modularity", {})
    if modularity.get("definition") != "weighted_undirected_newman_girvan":
        raise ValueError("unknown modularity definition")
    if algorithm.get("weight") != "trip_count" or modularity.get("weight") != "trip_count":
        raise ValueError("weight attribute mismatch")
    if float(algorithm["resolution"]) != float(modularity.get("resolution", -1)):
        raise ValueError("resolution mismatch")
    return contract


def project_od(frame: pd.DataFrame, mode: str = "sum", remove_self_loops: bool = True) -> nx.Graph:
    if mode not in PROJECTION_MODES:
        raise ValueError("unknown projection mode")
    required = {"origin_station_id", "destination_station_id", "trip_count"}
    if not required.issubset(frame.columns):
        raise ValueError("OD input is missing required columns")
    if frame[list(required)].isna().any().any():
        raise ValueError("OD input contains null key or weight")
    if frame.duplicated(["origin_station_id", "destination_station_id"]).any():
        raise ValueError("OD input contains duplicate directed keys")
    if not (frame.trip_count > 0).all():
        raise ValueError("OD input contains non-positive weight")
    graph = nx.Graph()
    nodes = sorted(set(frame.origin_station_id) | set(frame.destination_station_id))
    graph.add_nodes_from(nodes)
    ordered = frame.sort_values(["origin_station_id", "destination_station_id"], kind="mergesort")
    for row in ordered.itertuples(index=False):
        origin, destination, weight = str(row.origin_station_id), str(row.destination_station_id), int(row.trip_count)
        if origin == destination and remove_self_loops:
            continue
        if mode == "unweighted":
            value = 1
        elif graph.has_edge(origin, destination):
            previous = graph[origin][destination]["trip_count"]
            value = previous + weight if mode == "sum" else max(previous, weight)
        else:
            value = weight
        graph.add_edge(origin, destination, trip_count=value)
    return graph


def deterministic_relabel(communities: Iterable[set[str]]) -> dict[str, int]:
    normalized = [set(map(str, community)) for community in communities]
    if any(not community for community in normalized):
        raise ValueError("empty community")
    all_nodes = [node for community in normalized for node in community]
    if len(all_nodes) != len(set(all_nodes)):
        raise ValueError("communities overlap")
    ordered = sorted(normalized, key=lambda community: min(community))
    return {node: label for label, community in enumerate(ordered, start=1) for node in sorted(community)}


def manual_weighted_modularity(graph: nx.Graph, communities: Iterable[set[str]], resolution: float) -> float:
    total_weight = float(graph.size(weight="trip_count"))
    if total_weight <= 0:
        raise ValueError("modularity requires positive graph weight")
    result = 0.0
    for community in communities:
        subgraph = graph.subgraph(community)
        internal = float(subgraph.size(weight="trip_count"))
        strength = sum(float(graph.degree(node, weight="trip_count")) for node in community)
        result += internal / total_weight - resolution * (strength / (2 * total_weight)) ** 2
    return result


def synthetic_validation(contract: dict[str, Any]) -> dict[str, Any]:
    frame = pd.DataFrame({
        "origin_station_id": ["A", "B", "A", "B", "C", "D", "E", "D", "E", "F", "C", "G"],
        "destination_station_id": ["B", "A", "C", "C", "A", "E", "D", "F", "F", "D", "D", "G"],
        "trip_count": [8, 7, 9, 8, 7, 8, 7, 9, 8, 7, 1, 20],
    })
    summed = project_od(frame, "sum", True)
    maximum = project_od(frame, "max", True)
    unweighted = project_od(frame, "unweighted", True)
    expected_partition = [{"A", "B", "C"}, {"D", "E", "F"}, {"G"}]
    resolution = float(contract["algorithm"]["resolution"])
    library_q = nx.community.modularity(summed, expected_partition, weight="trip_count", resolution=resolution)
    manual_q = manual_weighted_modularity(summed, expected_partition, resolution)
    kwargs = {"weight": "trip_count", "resolution": resolution,
              "threshold": float(contract["algorithm"]["threshold"]),
              "seed": int(contract["algorithm"]["seed"])}
    first = nx.community.louvain_communities(summed, **kwargs)
    second = nx.community.louvain_communities(summed, **kwargs)
    first_labels, second_labels = deterministic_relabel(first), deterministic_relabel(second)
    checks = {
        "reciprocal_sum": summed["A"]["B"]["trip_count"] == 15,
        "reciprocal_max": maximum["A"]["B"]["trip_count"] == 8,
        "unweighted_presence": unweighted["A"]["B"]["trip_count"] == 1,
        "one_way_retained": summed["C"]["D"]["trip_count"] == 1,
        "no_duplicate_projected_edges": summed.number_of_edges() == 7,
        "self_loop_removed": nx.number_of_selfloops(summed) == 0,
        "isolated_after_loop_removal": list(nx.isolates(summed)) == ["G"],
        "isolated_in_louvain_partition": any(community == {"G"} for community in first),
        "manual_modularity_matches_library": math.isclose(library_q, manual_q, abs_tol=1e-12),
        "fixed_seed_deterministic": first_labels == second_labels,
    }
    if not all(checks.values()):
        raise RuntimeError(f"synthetic validation failed: {checks}")
    return {"checks": checks, "expected_partition_modularity": library_q,
            "fixed_seed_partition_labels": first_labels, "node_count": summed.number_of_nodes()}


def projection_qa(frame: pd.DataFrame, projected: nx.Graph) -> dict[str, Any]:
    loops = frame.origin_station_id == frame.destination_station_id
    nonloops = frame.loc[~loops].copy()
    unordered = nonloops.apply(lambda row: tuple(sorted((str(row.origin_station_id), str(row.destination_station_id)))), axis=1)
    multiplicity = unordered.value_counts()
    loop_weight = int(frame.loc[loops, "trip_count"].sum())
    projected_weight = int(projected.size(weight="trip_count"))
    checks = {
        "projected_edge_identity": projected.number_of_edges() == int(multiplicity.size),
        "pair_accounting": int((multiplicity == 2).sum() + (multiplicity == 1).sum()) == projected.number_of_edges(),
        "weight_conservation": projected_weight == int(nonloops.trip_count.sum()),
        "full_weight_reconciliation": projected_weight + loop_weight == int(frame.trip_count.sum()),
        "self_loops_removed": nx.number_of_selfloops(projected) == 0,
    }
    if not all(checks.values()):
        raise RuntimeError(f"projection QA failed: {checks}")
    return {
        "directed_edge_count": len(frame), "directed_weight_sum": int(frame.trip_count.sum()),
        "self_loop_edges_removed": int(loops.sum()), "self_loop_weight_removed": loop_weight,
        "reciprocal_pair_count": int((multiplicity == 2).sum()),
        "one_way_pair_count": int((multiplicity == 1).sum()),
        "projected_undirected_edge_count": projected.number_of_edges(),
        "projected_weight_sum": projected_weight,
        "isolated_node_count_after_loop_removal": nx.number_of_isolates(projected),
        "checks": checks,
    }


def bounded_real_validation(projected: nx.Graph, contract: dict[str, Any]) -> dict[str, Any]:
    max_nodes = int(contract["phase_6_0_guard"]["bounded_real_louvain_max_nodes"])
    candidates = [node for node, degree in projected.degree() if degree > 0]
    anchor = min(candidates)
    selected = [anchor] + sorted(set(projected.neighbors(anchor)))[:max_nodes - 1]
    subgraph = projected.subgraph(selected).copy()
    if subgraph.number_of_nodes() > max_nodes:
        raise RuntimeError("bounded validation exceeded node guard")
    kwargs = {"weight": "trip_count", "resolution": float(contract["algorithm"]["resolution"]),
              "threshold": float(contract["algorithm"]["threshold"]),
              "seed": int(contract["algorithm"]["seed"])}
    first = deterministic_relabel(nx.community.louvain_communities(subgraph, **kwargs))
    second = deterministic_relabel(nx.community.louvain_communities(subgraph, **kwargs))
    if first != second:
        raise RuntimeError("bounded fixed-seed validation was not deterministic")
    fingerprint = hashlib.sha256(json.dumps(first, sort_keys=True).encode("utf-8")).hexdigest()
    return {"purpose": "implementation_only_not_core_result", "node_count": subgraph.number_of_nodes(),
            "edge_count": subgraph.number_of_edges(), "fixed_seed_deterministic": True,
            "partition_fingerprint": fingerprint}


def run(args: argparse.Namespace) -> dict[str, Any]:
    contract = load_contract(args.contract)
    frame = pq.ParquetFile(args.core_od).read().to_pandas()
    projected = project_od(frame, contract["target_graph"]["projection_mode"], True)
    result = {
        "contract_version": contract["contract_version"],
        "contract_sha256": sha256_file(args.contract),
        "core_od_sha256": sha256_file(args.core_od),
        "library": {"name": "networkx", "version": nx.__version__,
                    "function": contract["algorithm"]["function"],
                    "directed_input_supported_by_library": True},
        "full_core_louvain_executed": False,
        "projection_qa": projection_qa(frame, projected),
        "synthetic_validation": synthetic_validation(contract),
        "bounded_real_validation": bounded_real_validation(projected, contract),
        "validation_status": "passed",
    }
    write_json(args.output, result)
    return result


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=root / "config/louvain_contract.yaml")
    parser.add_argument("--core-od", type=Path, default=root / "data/processed/od/aggregate/core_2023_2024/od.parquet")
    parser.add_argument("--output", type=Path, default=root / "notes/louvain-contract-validation.json")
    result = run(parser.parse_args())
    print(json.dumps({"status": result["validation_status"], "full_core_louvain_executed": False}))


if __name__ == "__main__":
    main()
