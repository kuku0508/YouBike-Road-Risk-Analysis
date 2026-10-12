"""Validate Phase 7.0 K-means inputs and plumbing without full-core clustering."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import sklearn
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

from validate_louvain_contract import sha256_file, write_json

CONTRACT_VERSION = "kmeans-reconstruction-contract-v1"
FEATURES = ["total_strength", "betweenness_primary", "clustering_primary", "pagerank_primary"]
SCALERS = {"StandardScaler", "none", "MinMaxScaler", "log1p_total_strength_then_StandardScaler"}


def load_contract(path: Path) -> dict[str, Any]:
    contract = json.loads(path.read_text(encoding="utf-8"))
    if contract.get("contract_version") != CONTRACT_VERSION:
        raise ValueError("unknown K-means contract version")
    if contract.get("features") != FEATURES:
        raise ValueError("feature contract mismatch")
    preprocessing = contract.get("preprocessing", {})
    if preprocessing.get("primary_scaler") not in SCALERS:
        raise ValueError("unknown scaler")
    if preprocessing.get("primary_scaler") != "StandardScaler":
        raise ValueError("primary scaler mismatch")
    if preprocessing.get("log_transform") is not False:
        raise ValueError("primary log transform must be false")
    if preprocessing.get("outlier_policy") != "retain_all_no_winsorization_or_trimming":
        raise ValueError("outlier policy mismatch")
    model = contract.get("kmeans", {})
    expected = {"library": "scikit-learn", "library_version": sklearn.__version__,
                "class": "sklearn.cluster.KMeans", "init": "k-means++", "n_init": 50,
                "max_iter": 300, "tol": 0.0001, "algorithm": "lloyd", "random_state": 42}
    for key, value in expected.items():
        if model.get(key) != value:
            raise ValueError(f"KMeans {key} mismatch")
    if contract.get("elbow", {}).get("k_values") != list(range(1, 11)):
        raise ValueError("elbow k range mismatch")
    if contract.get("phase_7_0_guard", {}).get("full_core_kmeans_allowed") is not False:
        raise ValueError("Phase 7.0 must forbid full-core KMeans")
    return contract


def extract_features(frame: pd.DataFrame, contract: dict[str, Any]) -> tuple[pd.Series, pd.DataFrame]:
    node_key = contract["input"]["node_key"]
    required = [node_key] + contract["features"]
    missing = [column for column in required if column not in frame]
    if missing:
        raise ValueError(f"missing feature columns: {missing}")
    selected = frame[required].copy()
    if selected[node_key].isna().any() or not selected[node_key].is_unique:
        raise ValueError("station_id must be complete and unique")
    matrix = selected[contract["features"]]
    if matrix.isna().any().any() or not np.isfinite(matrix.to_numpy(dtype=float)).all():
        raise ValueError("features contain NaN or infinite values")
    if len(selected) != int(contract["input"]["expected_node_count"]):
        raise ValueError("node count mismatch")
    return selected[node_key].astype(str), matrix.astype(float)


def feature_profile(matrix: pd.DataFrame) -> dict[str, Any]:
    output = {}
    for column in matrix:
        series = matrix[column]
        output[column] = {
            "min": float(series.min()), "max": float(series.max()),
            "mean": float(series.mean()), "median": float(series.median()),
            "std_sample": float(series.std(ddof=1)),
            "p1": float(series.quantile(0.01)), "p5": float(series.quantile(0.05)),
            "p25": float(series.quantile(0.25)), "p75": float(series.quantile(0.75)),
            "p95": float(series.quantile(0.95)), "p99": float(series.quantile(0.99)),
            "skewness": float(series.skew()),
        }
    return output


def deterministic_relabel(raw_labels: Iterable[int], station_ids: Iterable[str]) -> np.ndarray:
    labels = np.asarray(list(raw_labels), dtype=int)
    stations = np.asarray(list(station_ids), dtype=str)
    if len(labels) != len(stations):
        raise ValueError("label and station lengths differ")
    cluster_keys = []
    for label in np.unique(labels):
        members = stations[labels == label]
        if not len(members):
            raise ValueError("empty cluster")
        cluster_keys.append((min(members.tolist()), int(label)))
    mapping = {old: new for new, (_, old) in enumerate(sorted(cluster_keys), start=1)}
    return np.asarray([mapping[int(label)] for label in labels], dtype=int)


def make_kmeans(contract: dict[str, Any], n_clusters: int, random_state: int | None = None) -> KMeans:
    settings = contract["kmeans"]
    return KMeans(n_clusters=n_clusters, init=settings["init"], n_init=settings["n_init"],
                  max_iter=settings["max_iter"], tol=settings["tol"], algorithm=settings["algorithm"],
                  random_state=settings["random_state"] if random_state is None else random_state)


def geometric_knee(k_values: list[int], inertias: list[float]) -> dict[str, Any]:
    if len(k_values) != len(inertias) or len(k_values) < 3:
        raise ValueError("knee diagnostic requires at least three paired values")
    x = np.asarray(k_values, dtype=float); y = np.asarray(inertias, dtype=float)
    if not np.isfinite(y).all() or np.any(np.diff(x) <= 0) or np.any(np.diff(y) > 1e-9):
        raise ValueError("invalid elbow curve")
    x_norm = (x - x.min()) / (x.max() - x.min())
    y_norm = (y - y.min()) / (y.max() - y.min()) if y.max() > y.min() else np.zeros_like(y)
    start, end = np.array([x_norm[0], y_norm[0]]), np.array([x_norm[-1], y_norm[-1]])
    chord = end - start
    distances = np.abs(chord[0] * (start[1] - y_norm) - (start[0] - x_norm) * chord[1]) / np.linalg.norm(chord)
    max_distance = float(distances.max())
    candidates = [int(k) for k, distance in zip(k_values, distances) if math.isclose(float(distance), max_distance, abs_tol=1e-15)]
    return {"selected_k": min(candidates), "distances": {str(k): float(d) for k, d in zip(k_values, distances)}}


def synthetic_validation(contract: dict[str, Any]) -> dict[str, Any]:
    matrix = pd.DataFrame([
        [10, .0010, .80, .00010], [12, .0012, .78, .00012], [9, .0009, .82, .00009],
        [1000, .0100, .40, .00100], [1100, .0110, .42, .00110], [950, .0090, .38, .00095],
        [5000, .0300, .10, .00400], [5200, .0320, .12, .00420], [4800, .0290, .08, .00380],
        [50000, .0800, .02, .01000],
    ], columns=FEATURES, dtype=float)
    stations = pd.Series([f"S{i:02d}" for i in range(len(matrix))])
    original = matrix.copy(deep=True)
    scaler = StandardScaler(with_mean=True, with_std=True)
    scaled = scaler.fit_transform(matrix)
    inverse = scaler.inverse_transform(scaled)
    first = make_kmeans(contract, 3).fit(scaled)
    second = make_kmeans(contract, 3).fit(scaled)
    labels_first = deterministic_relabel(first.labels_, stations)
    labels_second = deterministic_relabel(second.labels_, stations)
    inertias = []
    for k in range(1, 6):
        inertias.append(float(make_kmeans(contract, k).fit(scaled).inertia_))
    knee = geometric_knee(list(range(1, 6)), inertias)
    checks = {
        "scaled_mean_zero": bool(np.allclose(scaled.mean(axis=0), 0, atol=1e-12)),
        "scaled_variance_one": bool(np.allclose(scaled.var(axis=0), 1, atol=1e-12)),
        "inverse_transform_exact": bool(np.allclose(inverse, matrix.to_numpy(), atol=1e-10)),
        "fixed_seed_deterministic": bool(np.array_equal(labels_first, labels_second)),
        "inertia_reproducible": math.isclose(float(first.inertia_), float(second.inertia_), abs_tol=1e-15),
        "n_init_propagated": bool(first.n_init == 50),
        "all_rows_retained": len(labels_first) == len(original) == 10,
        "extreme_value_retained": bool(original.total_strength.max() == 50000),
        "inertia_monotone": bool(np.all(np.diff(inertias) <= 1e-9)),
    }
    if not all(checks.values()):
        raise RuntimeError(f"synthetic KMeans validation failed: {checks}")
    return {"checks": checks, "sample_count": len(matrix), "feature_count": len(FEATURES),
            "k3_inertia": float(first.inertia_), "knee_diagnostic": knee,
            "partition_fingerprint": hashlib.sha256(labels_first.tobytes()).hexdigest()}


def bounded_real_validation(stations: pd.Series, matrix: pd.DataFrame,
                            contract: dict[str, Any]) -> dict[str, Any]:
    maximum = int(contract["phase_7_0_guard"]["bounded_real_kmeans_max_rows"])
    selected = np.linspace(0, len(matrix) - 1, num=12, dtype=int)
    subset = matrix.iloc[selected]
    subset_stations = stations.iloc[selected]
    if len(subset) > maximum:
        raise RuntimeError("bounded KMeans exceeded row guard")
    scaled = StandardScaler().fit_transform(subset)
    first = make_kmeans(contract, 3).fit(scaled)
    second = make_kmeans(contract, 3).fit(scaled)
    labels_first = deterministic_relabel(first.labels_, subset_stations)
    labels_second = deterministic_relabel(second.labels_, subset_stations)
    if not np.array_equal(labels_first, labels_second):
        raise RuntimeError("bounded KMeans was not deterministic")
    return {"purpose": "parameter_plumbing_only_not_full_result", "row_count": len(subset),
            "feature_count": subset.shape[1], "fixed_seed_deterministic": True,
            "partition_fingerprint": hashlib.sha256(labels_first.tobytes()).hexdigest()}


def run(args: argparse.Namespace) -> dict[str, Any]:
    contract = load_contract(args.contract)
    if sha256_file(args.metrics) != contract["input"]["sha256"]:
        raise RuntimeError("node metrics hash mismatch")
    frame = pq.ParquetFile(args.metrics).read().to_pandas()
    stations, matrix = extract_features(frame, contract)
    scaler = StandardScaler(with_mean=True, with_std=True)
    scaled = scaler.fit_transform(matrix)
    scale_checks = {
        "mean_zero": bool(np.allclose(scaled.mean(axis=0), 0, atol=1e-12)),
        "variance_one_population": bool(np.allclose(scaled.var(axis=0), 1, atol=1e-12)),
        "inverse_transform": bool(np.allclose(scaler.inverse_transform(scaled), matrix.to_numpy(), atol=1e-8)),
    }
    if not all(scale_checks.values()):
        raise RuntimeError(f"full feature scaling validation failed: {scale_checks}")
    result = {
        "contract_version": contract["contract_version"], "contract_sha256": sha256_file(args.contract),
        "node_metrics_sha256": sha256_file(args.metrics), "node_count": len(matrix),
        "selected_features": FEATURES, "feature_profile": feature_profile(matrix),
        "pearson_correlation": matrix.corr("pearson").to_dict(),
        "spearman_correlation": matrix.corr("spearman").to_dict(),
        "scale_disparity": {"raw_range_ratio_total_strength_to_clustering":
                            float((matrix.total_strength.max() - matrix.total_strength.min()) /
                                  (matrix.clustering_primary.max() - matrix.clustering_primary.min()))},
        "primary_scaler_validation": scale_checks,
        "synthetic_validation": synthetic_validation(contract),
        "bounded_real_validation": bounded_real_validation(stations, matrix, contract),
        "full_core_kmeans_executed": False,
        "validation_status": "passed",
    }
    write_json(args.output, result)
    return result


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=root / "config/kmeans_contract.yaml")
    parser.add_argument("--metrics", type=Path, default=root / "data/processed/network/core_2023_2024/node_metrics.parquet")
    parser.add_argument("--output", type=Path, default=root / "notes/kmeans-contract-validation.json")
    result = run(parser.parse_args())
    print(json.dumps({"status": result["validation_status"], "full_core_kmeans_executed": False}))


if __name__ == "__main__":
    main()
