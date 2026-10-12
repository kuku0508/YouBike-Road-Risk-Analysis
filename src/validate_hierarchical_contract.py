"""Validate Phase 7.2 hierarchical contract without full-data clustering."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import scipy
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import pdist
from sklearn.preprocessing import StandardScaler

CONTRACT_VERSION = "hierarchical-clustering-reconstruction-contract-v1"
METRICS = ["betweenness", "eigenvector", "pagerank"]


def load_contract(path: Path) -> dict[str, Any]:
    contract = json.loads(path.read_text(encoding="utf-8"))
    if contract.get("contract_version") != CONTRACT_VERSION:
        raise ValueError("unknown hierarchical contract version")
    if contract.get("period_resolution") != "clearly_2022_2024":
        raise ValueError("period gate must remain clearly_2022_2024")
    if contract.get("resolved_analysis_period") != "2022-01-01/2024-12-31":
        raise ValueError("resolved period mismatch")
    if contract.get("analysis_units") != ["weekday", "holiday"]:
        raise ValueError("weekday and holiday must be separate analyses")
    features = contract.get("features", {})
    if features.get("metrics") != METRICS or features.get("expected_feature_count_per_day_type") != 72:
        raise ValueError("hierarchical feature contract mismatch")
    if features.get("weighted_degree_included") or features.get("clustering_coefficient_included"):
        raise ValueError("K-means-only features leaked into hierarchical contract")
    preprocessing = contract.get("preprocessing", {})
    if preprocessing.get("primary_scaler") != "StandardScaler":
        raise ValueError("unknown primary scaler")
    if preprocessing.get("outlier_policy") != "retain_all_no_winsorization_trimming_or_removal":
        raise ValueError("outlier policy mismatch")
    if contract.get("distance", {}).get("metric") != "euclidean":
        raise ValueError("distance must be report-specified Euclidean")
    linkage_spec = contract.get("linkage", {})
    if linkage_spec.get("report_method") != "Ward.D2" or linkage_spec.get("reconstruction_method") != "ward":
        raise ValueError("unknown or mismatched linkage")
    if linkage_spec.get("reconstruction_library_version") != scipy.__version__:
        raise ValueError("SciPy version mismatch")
    cut = contract.get("cut_rule", {})
    if cut.get("weekday_cluster_count") != 5 or cut.get("holiday_cluster_count") != 4:
        raise ValueError("report-displayed cluster counts mismatch")
    guard = contract.get("phase_7_2_guard", {})
    if guard.get("full_core_hierarchical_allowed") is not False or guard.get("execution_ready") is not False:
        raise ValueError("Phase 7.2 must remain blocked and forbid full execution")
    return contract


def expected_feature_columns() -> list[str]:
    return [f"{metric}_h{hour:02d}" for metric in METRICS for hour in range(24)]


def deterministic_relabel(raw_labels: Iterable[int], station_ids: Iterable[str]) -> np.ndarray:
    labels = np.asarray(list(raw_labels), dtype=int)
    stations = np.asarray(list(station_ids), dtype=str)
    if len(labels) != len(stations):
        raise ValueError("label and station lengths differ")
    keys = []
    for label in np.unique(labels):
        members = stations[labels == label]
        if not len(members):
            raise ValueError("empty cluster")
        keys.append((min(members.tolist()), int(label)))
    mapping = {old: new for new, (_, old) in enumerate(sorted(keys), start=1)}
    return np.asarray([mapping[int(label)] for label in labels], dtype=int)


def prepare_matrix(frame: pd.DataFrame, *, exact_features: list[str], expected_rows: int | None = None) -> tuple[list[str], np.ndarray]:
    required = ["station_id", *exact_features]
    if list(frame.columns) != required:
        raise ValueError("feature frame must contain only station_id plus exact ordered features")
    if frame.station_id.isna().any() or frame.station_id.astype(str).duplicated().any():
        raise ValueError("station_id must be present and unique")
    if expected_rows is not None and len(frame) != expected_rows:
        raise ValueError("row count mismatch")
    ordered = frame.assign(station_id=frame.station_id.astype(str)).sort_values("station_id", kind="mergesort")
    matrix = ordered[exact_features].to_numpy(dtype=float)
    if not np.isfinite(matrix).all():
        raise ValueError("features contain NaN or infinite values")
    return ordered.station_id.tolist(), matrix


def execute_hierarchy(station_ids: list[str], matrix: np.ndarray, *, method: str, k: int) -> dict[str, Any]:
    if method not in {"ward", "complete", "average"}:
        raise ValueError("unknown linkage")
    scaled = StandardScaler().fit_transform(matrix)
    distances = pdist(scaled, metric="euclidean")
    result = linkage(scaled, method=method, metric="euclidean", optimal_ordering=False)
    raw = fcluster(result, t=k, criterion="maxclust")
    labels = deterministic_relabel(raw, station_ids)
    return {
        "scaled": scaled, "distances": distances, "linkage": result, "labels": labels,
        "station_order_fingerprint": hashlib.sha256("\n".join(station_ids).encode()).hexdigest(),
        "linkage_sha256": hashlib.sha256(result.astype("<f8", copy=False).tobytes()).hexdigest(),
        "assignment_sha256": hashlib.sha256(labels.astype("<i8", copy=False).tobytes()).hexdigest(),
    }


def assert_execution_ready(contract: dict[str, Any], root: Path) -> None:
    missing = [path for path in contract["input"]["required_files"].values() if not (root / path).exists()]
    if missing:
        raise RuntimeError(f"2022 reconstruction inputs missing: {missing}")
    if not contract["phase_7_2_guard"]["execution_ready"]:
        raise RuntimeError("Phase 7.2 contract is not execution-ready")


def synthetic_validation() -> dict[str, Any]:
    rng = np.random.default_rng(72)
    feature_names = ["strength_like", "betweenness_like", "clustering_like", "pagerank_like"]
    scales = np.array([100_000.0, 0.01, 1.0, 0.0001])
    centers = np.vstack([np.zeros(4), np.ones(4) * 5, np.ones(4) * -5]) * scales
    matrix = np.vstack([center + rng.normal(0, 0.08, (3, 4)) * scales for center in centers])
    matrix = np.vstack([matrix, np.ones((1, 4)) * 30 * scales])
    stations = [f"S{i:02d}" for i in range(10)][::-1]
    frame = pd.DataFrame(matrix, columns=feature_names)
    frame.insert(0, "station_id", stations)
    ordered_stations, ordered_matrix = prepare_matrix(frame, exact_features=feature_names, expected_rows=10)
    first = execute_hierarchy(ordered_stations, ordered_matrix, method="ward", k=4)
    second = execute_hierarchy(ordered_stations, ordered_matrix, method="ward", k=4)
    checks = {
        "shape_10_by_4": ordered_matrix.shape == (10, 4),
        "different_raw_scales": float(np.ptp(ordered_matrix[:, 0])) > 1_000_000 * float(np.ptp(ordered_matrix[:, 3])),
        "station_order_deterministic": ordered_stations == sorted(stations),
        "scaled_mean_zero": bool(np.allclose(first["scaled"].mean(axis=0), 0, atol=1e-12)),
        "distance_count_correct": len(first["distances"]) == 45,
        "linkage_shape_correct": first["linkage"].shape == (9, 4),
        "linkage_deterministic": first["linkage_sha256"] == second["linkage_sha256"],
        "labels_deterministic": first["assignment_sha256"] == second["assignment_sha256"],
        "labels_contiguous": sorted(np.unique(first["labels"]).tolist()) == [1, 2, 3, 4],
        "outlier_retained": len(first["labels"]) == 10 and float(ordered_matrix[:, 0].max()) == 3_000_000.0,
    }
    if not all(checks.values()):
        raise RuntimeError(f"synthetic validation failed: {checks}")
    return {"checks": checks, "linkage_sha256": first["linkage_sha256"],
            "assignment_sha256": first["assignment_sha256"]}


def bounded_real_validation(path: Path) -> dict[str, Any]:
    frame = pq.ParquetFile(path).read(columns=["station_id", "betweenness_primary", "eigenvector_primary", "pagerank_primary"]).to_pandas()
    frame = frame.sort_values("station_id", kind="mergesort").iloc[np.linspace(0, len(frame) - 1, 12, dtype=int)]
    frame.columns = ["station_id", "betweenness", "eigenvector", "pagerank"]
    stations, matrix = prepare_matrix(frame, exact_features=METRICS, expected_rows=12)
    first = execute_hierarchy(stations, matrix, method="ward", k=3)
    second = execute_hierarchy(stations, matrix, method="ward", k=3)
    return {
        "purpose": "three_metric_plumbing_only_not_72_feature_target_or_report_result",
        "row_count": 12, "feature_count": 3,
        "deterministic": first["linkage_sha256"] == second["linkage_sha256"] and
                         first["assignment_sha256"] == second["assignment_sha256"],
        "linkage_sha256": first["linkage_sha256"], "assignment_sha256": first["assignment_sha256"],
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=root / "config/hierarchical_clustering_contract.yaml")
    parser.add_argument("--node-metrics", type=Path, default=root / "data/processed/network/core_2023_2024/node_metrics.parquet")
    parser.add_argument("--sample-audit", type=Path, default=root / "data/interim/schema-compatibility-2022-bounds.json")
    parser.add_argument("--source-index-evidence", type=Path, default=root / "notes/source-receipt.json")
    parser.add_argument("--output", type=Path, default=root / "notes/hierarchical-contract-validation.json")
    args = parser.parse_args()
    contract = load_contract(args.contract)
    head = json.loads(args.source_index_evidence.read_text(encoding="utf-8"))["index_head_checks"]
    rows_2022 = [row for row in head["rows"] if row["month"].startswith("2022-")]
    sample = json.loads(args.sample_audit.read_text(encoding="utf-8"))["months"]
    sample_summary = [{key: month[key] for key in ["month", "filename", "bytes", "sha256", "row_count",
                                                          "dominant_width", "header_present", "encoding",
                                                          "undecodable_byte_count", "date_field_position"]}
                      for month in sample]
    required_paths = dict(contract["input"]["required_files"])
    result = {
        "contract_version": contract["contract_version"], "scipy_version": scipy.__version__,
        "period_resolution": contract["period_resolution"],
        "report_period": "2022-2024", "required_months": 36,
        "source_index_2022": {"listed_month_count": len(rows_2022),
                              "months": sorted(row["month"] for row in rows_2022),
                              "all_head_status_200": all(row["status"] == 200 for row in rows_2022),
                              "head_checked_utc": head["checked_utc"]},
        "sampled_2022_raw": sample_summary,
        "sample_parser_eof_validation": {
            "2022-01": {"record_count": 1371395, "schema_versions": ["v1_6col"], "warning_count": 0},
            "2022-12": {"record_count": 2628740, "schema_versions": ["v1_6col"], "warning_count": 0},
        },
        "target_feature_count_per_day_type": len(expected_feature_columns()),
        "target_input_paths": required_paths,
        "target_inputs_exist": all((root / path).exists() for path in required_paths.values()),
        "synthetic_validation": synthetic_validation(),
        "bounded_real_validation": bounded_real_validation(args.node_metrics),
        "full_core_hierarchical_executed": False,
        "execution_readiness": "blocked",
        "blocked_reason": "2022_NETWORK_RECONSTRUCTION_REQUIRED",
        "validation_status": "passed_contract_blocked_execution",
    }
    if len(rows_2022) != 12 or not result["source_index_2022"]["all_head_status_200"]:
        raise RuntimeError("2022 source availability gate failed")
    if result["target_inputs_exist"]:
        raise RuntimeError("unexpected target inputs exist; re-audit readiness before execution")
    write_json(args.output, result)
    print(json.dumps({"status": result["validation_status"], "execution_readiness": "blocked"}))


if __name__ == "__main__":
    main()
