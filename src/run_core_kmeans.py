"""Execute Phase 7.1 full-core elbow analysis and report-reference k=4 K-means."""
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

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import sklearn
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score, silhouette_score
from sklearn.preprocessing import MinMaxScaler, StandardScaler

from validate_kmeans_contract import (deterministic_relabel, geometric_knee,
                                      load_contract, sha256_file, write_json)

PIPELINE_VERSION = "core-kmeans-v1"


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


def atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp.parquet")
    pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), temporary, compression="zstd")
    os.replace(temporary, path)


def atomic_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp.csv")
    frame.to_csv(temporary, index=False, encoding="utf-8-sig")
    os.replace(temporary, path)


def assignment_fingerprint(station_ids: list[str], labels: np.ndarray) -> str:
    pairs = sorted(zip(map(str, station_ids), map(int, labels)))
    return hashlib.sha256("".join(f"{sid}\t{label}\n" for sid, label in pairs).encode()).hexdigest()


def fit_kmeans(matrix: np.ndarray, contract: dict[str, Any], *, k: int, seed: int) -> dict[str, Any]:
    spec = contract["kmeans"]
    started = time.perf_counter()
    model = KMeans(n_clusters=k, init=spec["init"], n_init=int(spec["n_init"]),
                   max_iter=int(spec["max_iter"]), tol=float(spec["tol"]),
                   algorithm=spec["algorithm"], random_state=seed)
    raw_labels = model.fit_predict(matrix)
    runtime = time.perf_counter() - started
    return {"model": model, "raw_labels": raw_labels, "inertia": float(model.inertia_),
            "n_iter": int(model.n_iter_), "runtime_seconds": runtime}


def relabel_fit(result: dict[str, Any], station_ids: list[str]) -> dict[str, Any]:
    labels = deterministic_relabel(result["raw_labels"], station_ids).astype(np.int64)
    raw_to_final = {}
    for raw in np.unique(result["raw_labels"]):
        final_values = np.unique(labels[result["raw_labels"] == raw])
        if len(final_values) != 1:
            raise RuntimeError("deterministic relabel split one raw cluster")
        raw_to_final[int(raw)] = int(final_values[0])
    centroids = np.empty_like(result["model"].cluster_centers_)
    for raw, final in raw_to_final.items():
        centroids[final - 1] = result["model"].cluster_centers_[raw]
    return {**result, "labels": labels, "centroids": centroids,
            "assignment_fingerprint": assignment_fingerprint(station_ids, labels)}


def compare_labels(primary: np.ndarray, variant: np.ndarray) -> tuple[float, float]:
    return (float(adjusted_rand_score(primary, variant)),
            float(normalized_mutual_info_score(primary, variant)))


def validate_metrics(metrics: pd.DataFrame, contract: dict[str, Any], source_path: Path) -> tuple[pd.DataFrame, np.ndarray]:
    expected_hash = contract["input"]["sha256"]
    if sha256_file(source_path) != expected_hash:
        raise RuntimeError("node metrics source hash mismatch")
    if sklearn.__version__ != contract["kmeans"]["library_version"]:
        raise RuntimeError("scikit-learn version mismatch")
    features = contract["features"]
    required = ["station_id", "station_name", "city", *features]
    if any(column not in metrics for column in required):
        raise RuntimeError("node metrics missing required columns")
    if len(metrics) != int(contract["input"]["expected_node_count"]):
        raise RuntimeError("node count mismatch")
    if metrics.station_id.isna().any() or metrics.station_id.astype(str).duplicated().any():
        raise RuntimeError("station_id must be present and unique")
    frame = metrics[required].copy()
    frame["station_id"] = frame.station_id.astype(str)
    matrix = frame[features].to_numpy(dtype=float)
    if matrix.shape != (2782, 4) or not np.isfinite(matrix).all():
        raise RuntimeError("feature matrix must be 2782 x 4 and finite")
    return frame, matrix


def elbow_analysis(matrix: np.ndarray, contract: dict[str, Any]) -> tuple[pd.DataFrame, int, int, float]:
    rows = []
    silhouette_total = 0.0
    for k in contract["elbow"]["k_values"]:
        fit = fit_kmeans(matrix, contract, k=int(k), seed=int(contract["kmeans"]["random_state"]))
        silhouette = None
        silhouette_runtime = None
        if int(k) in contract["secondary_diagnostics"]["silhouette_k_values"]:
            started = time.perf_counter()
            silhouette = float(silhouette_score(matrix, fit["raw_labels"]))
            silhouette_runtime = time.perf_counter() - started
            silhouette_total += silhouette_runtime
        rows.append({"k": int(k), "inertia": fit["inertia"], "fit_iterations": fit["n_iter"],
                     "fit_runtime_seconds": fit["runtime_seconds"], "silhouette": silhouette,
                     "silhouette_runtime_seconds": silhouette_runtime})
    table = pd.DataFrame(rows)
    knee = geometric_knee(table.k.astype(int).tolist(), table.inertia.astype(float).tolist())
    table["normalized_k"] = (table.k - table.k.min()) / (table.k.max() - table.k.min())
    table["normalized_inertia"] = ((table.inertia - table.inertia.min()) /
                                   (table.inertia.max() - table.inertia.min()))
    table["distance_to_chord"] = table.k.map(lambda value: knee["distances"][str(int(value))])
    detected_knee = int(knee["selected_k"])
    silhouette_best = int(table.loc[table.silhouette.idxmax(), "k"])
    return table, detected_knee, silhouette_best, silhouette_total


def station_representative(group: pd.DataFrame, metric: str) -> tuple[str, str]:
    row = group.sort_values([metric, "station_id"], ascending=[False, True], kind="mergesort").iloc[0]
    return str(row.station_id), str(row.station_name)


def build_outputs(frame: pd.DataFrame, raw_matrix: np.ndarray, scaled_matrix: np.ndarray,
                  labels: np.ndarray, scaled_centroids: np.ndarray, scaler: StandardScaler,
                  features: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    partition = frame.copy()
    partition["cluster_id"] = labels
    scaled_columns = [f"z_{feature}" for feature in features]
    for index, column in enumerate(scaled_columns):
        partition[column] = scaled_matrix[:, index]
    partition = partition[["station_id", "station_name", "city", "cluster_id", *features, *scaled_columns]]
    partition = partition.sort_values("station_id").reset_index(drop=True)
    original_centroids = scaler.inverse_transform(scaled_centroids)
    rows = []
    for cluster_id in range(1, 5):
        group = partition[partition.cluster_id == cluster_id].copy()
        centroid = scaled_centroids[cluster_id - 1]
        group_matrix = group[scaled_columns].to_numpy(dtype=float)
        distances = np.linalg.norm(group_matrix - centroid, axis=1)
        prototype = group.iloc[int(np.argmin(distances))]
        row: dict[str, Any] = {"cluster_id": cluster_id, "node_count": int(len(group)),
                               "proportion": float(len(group) / len(partition))}
        for index, feature in enumerate(features):
            row[f"scaled_centroid_{feature}"] = float(scaled_centroids[cluster_id - 1, index])
            row[f"original_centroid_{feature}"] = float(original_centroids[cluster_id - 1, index])
            row[f"p25_{feature}"] = float(group[feature].quantile(0.25))
            row[f"median_{feature}"] = float(group[feature].median())
            row[f"p75_{feature}"] = float(group[feature].quantile(0.75))
            station_id, station_name = station_representative(group, feature)
            row[f"top_{feature}_station_id"] = station_id
            row[f"top_{feature}_station_name"] = station_name
        row["prototype_station_id"] = str(prototype.station_id)
        row["prototype_station_name"] = str(prototype.station_name)
        row["prototype_scaled_distance"] = float(distances.min())
        rows.append(row)
    return partition, pd.DataFrame(rows)


def scaling_matrix(raw_matrix: np.ndarray, variant: str) -> np.ndarray:
    if variant == "none":
        return raw_matrix.copy()
    if variant == "MinMaxScaler":
        return MinMaxScaler().fit_transform(raw_matrix)
    if variant == "log1p_total_strength_then_StandardScaler":
        transformed = raw_matrix.copy()
        transformed[:, 0] = np.log1p(transformed[:, 0])
        return StandardScaler().fit_transform(transformed)
    raise ValueError(f"unsupported scaling sensitivity: {variant}")


def cluster_size_record(labels: np.ndarray) -> list[dict[str, int]]:
    values, counts = np.unique(labels, return_counts=True)
    return [{"cluster_id": int(label), "node_count": int(count)} for label, count in zip(values, counts)]


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    contract = load_contract(args.contract)
    metrics = pq.ParquetFile(args.node_metrics).read().to_pandas()
    frame, raw_matrix = validate_metrics(metrics, contract, args.node_metrics)
    features = list(contract["features"])
    scaler = StandardScaler(with_mean=True, with_std=True)
    scaled_matrix = scaler.fit_transform(raw_matrix)
    if not np.allclose(scaled_matrix.mean(axis=0), 0.0, atol=1e-12):
        raise RuntimeError("scaled feature means are not zero")
    if not np.allclose(scaled_matrix.var(axis=0), 1.0, atol=1e-12):
        raise RuntimeError("scaled feature variances are not one")

    elbow_started = time.perf_counter()
    elbow, detected_knee, silhouette_best, silhouette_runtime = elbow_analysis(scaled_matrix, contract)
    elbow_runtime = time.perf_counter() - elbow_started
    primary_raw = fit_kmeans(scaled_matrix, contract, k=4, seed=42)
    primary = relabel_fit(primary_raw, frame.station_id.tolist())
    repeat = relabel_fit(fit_kmeans(scaled_matrix, contract, k=4, seed=42), frame.station_id.tolist())
    if (primary["assignment_fingerprint"] != repeat["assignment_fingerprint"] or
            not np.array_equal(primary["labels"], repeat["labels"]) or
            not np.allclose(primary["centroids"], repeat["centroids"], atol=1e-12) or
            not math.isclose(primary["inertia"], repeat["inertia"], abs_tol=1e-12)):
        raise RuntimeError("primary reproducibility validation failed")

    partition, summary = build_outputs(frame, raw_matrix, scaled_matrix, primary["labels"],
                                       primary["centroids"], scaler, features)
    sensitivity_started = time.perf_counter()
    variants = []
    for seed in [42, *contract["sensitivity_variants"]["additional_random_states"]]:
        result = relabel_fit(fit_kmeans(scaled_matrix, contract, k=4, seed=int(seed)), frame.station_id.tolist())
        ari, nmi = compare_labels(primary["labels"], result["labels"])
        variants.append({"variant": f"seed_{seed}", "variant_type": "seed", "scaler": "StandardScaler",
                         "seed": int(seed), "inertia": result["inertia"],
                         "silhouette": float(silhouette_score(scaled_matrix, result["labels"])),
                         "cluster_sizes": cluster_size_record(result["labels"]),
                         "ari_vs_primary": ari, "nmi_vs_primary": nmi,
                         "runtime_seconds": result["runtime_seconds"],
                         "assignment_fingerprint": result["assignment_fingerprint"]})
    for variant in contract["sensitivity_variants"]["scaling"]:
        matrix = scaling_matrix(raw_matrix, variant)
        result = relabel_fit(fit_kmeans(matrix, contract, k=4, seed=42), frame.station_id.tolist())
        ari, nmi = compare_labels(primary["labels"], result["labels"])
        variants.append({"variant": variant, "variant_type": "scaling", "scaler": variant,
                         "seed": 42, "inertia": result["inertia"],
                         "silhouette": float(silhouette_score(matrix, result["labels"])),
                         "cluster_sizes": cluster_size_record(result["labels"]),
                         "ari_vs_primary": ari, "nmi_vs_primary": nmi,
                         "runtime_seconds": result["runtime_seconds"],
                         "assignment_fingerprint": result["assignment_fingerprint"],
                         "inertia_cross_scaler_comparable": False})
    sensitivity_runtime = time.perf_counter() - sensitivity_started

    sizes = np.asarray([item["node_count"] for item in cluster_size_record(primary["labels"])])
    report_comparison = {
        "report_elbow_k": 4, "reconstruction_detected_knee": detected_knee,
        "reconstruction_silhouette_best_k": silhouette_best, "report_reference_clustering_k": 4,
        "k_selection_classification": "exact" if detected_knee == 4 else "materially_different",
        "report_cluster_sizes": "cannot_verify", "report_station_assignments": "cannot_verify",
        "report_full_centroids": "cannot_verify",
        "report_partial_profile_evidence": {"role_group_2_avg_flow_approx": 610000,
                                            "role_group_1_avg_clustering_approx": 0.752},
    }
    primary_summary = {
        "pipeline_version": PIPELINE_VERSION, "contract_version": contract["contract_version"],
        "scope": contract["analysis_scope"], "node_count": len(partition), "features": features,
        "primary_k": 4, "primary_seed": 42, "primary_inertia": primary["inertia"],
        "primary_silhouette": float(elbow.loc[elbow.k == 4, "silhouette"].iloc[0]),
        "detected_knee": detected_knee, "silhouette_best_k": silhouette_best,
        "cluster_sizes": cluster_size_record(primary["labels"]),
        "cluster_size_distribution": {"min": int(sizes.min()), "median": float(np.median(sizes)),
                                      "mean": float(sizes.mean()), "max": int(sizes.max())},
        "scaled_centroids": summary[["cluster_id", *[f"scaled_centroid_{f}" for f in features]]].to_dict("records"),
        "original_scale_centroids": summary[["cluster_id", *[f"original_centroid_{f}" for f in features]]].to_dict("records"),
        "assignment_fingerprint": primary["assignment_fingerprint"],
        "repeat_assignment_fingerprint": repeat["assignment_fingerprint"],
        "fixed_seed_reproducible": True, "report_comparison": report_comparison,
        "feature_correlation_context": {"total_strength_pagerank_pearson": float(frame.total_strength.corr(frame.pagerank_primary)),
                                        "interpretation": "high correlation; not independent evidence"},
    }
    sensitivity = {"pipeline_version": PIPELINE_VERSION, "contract_version": contract["contract_version"],
                   "primary_variant": "StandardScaler_seed_42", "variants": variants,
                   "inertia_cross_scaler_comparable": False}

    atomic_parquet(partition, args.partition_output)
    atomic_parquet(summary, args.summary_output)
    atomic_csv(elbow, args.elbow_csv)
    atomic_csv(summary, args.summary_csv)
    write_json(args.primary_summary, primary_summary)
    write_json(args.sensitivity_output, sensitivity)

    reread_partition = pq.ParquetFile(args.partition_output).read().to_pandas()
    reread_summary = pq.ParquetFile(args.summary_output).read().to_pandas()
    validation = {
        "source_hash_gate": sha256_file(args.node_metrics) == contract["input"]["sha256"],
        "node_count_2782": len(reread_partition) == 2782,
        "station_id_unique": bool(reread_partition.station_id.is_unique),
        "all_nodes_assigned_once": len(reread_partition) == reread_partition.station_id.nunique(),
        "cluster_ids_contiguous_1_to_4": sorted(reread_partition.cluster_id.unique().tolist()) == [1, 2, 3, 4],
        "features_finite": bool(np.isfinite(reread_partition[features + [f'z_{f}' for f in features]].to_numpy()).all()),
        "raw_scaled_join_aligned": bool(np.allclose(reread_partition.sort_values('station_id')[features].to_numpy(),
                                                     frame.sort_values('station_id')[features].to_numpy())),
        "centroid_inverse_transform": bool(np.allclose(scaler.inverse_transform(primary["centroids"]),
                                                        reread_summary[[f'original_centroid_{f}' for f in features]].to_numpy())),
        "fixed_seed_reproducible": True,
        "elbow_k_1_to_10_complete": elbow.k.tolist() == list(range(1, 11)),
        "silhouette_k_2_to_10_complete": bool(elbow.loc[elbow.k >= 2, "silhouette"].notna().all()),
        "outliers_retained": len(reread_partition) == len(frame),
        "no_hierarchical_clustering": True,
    }
    if not all(validation.values()):
        raise RuntimeError(f"validation failed: {validation}")
    receipt = {
        "pipeline_version": PIPELINE_VERSION, "contract_version": contract["contract_version"],
        "contract_sha256": sha256_file(args.contract), "sklearn_version": sklearn.__version__,
        "source_metrics_sha256": sha256_file(args.node_metrics), "feature_list": features,
        "scaler": "StandardScaler", "scaler_parameters": {"mean": dict(zip(features, map(float, scaler.mean_))),
                                                            "scale": dict(zip(features, map(float, scaler.scale_)))},
        "k_range": list(range(1, 11)), "detected_knee": detected_knee,
        "silhouette_best_k": silhouette_best, "primary_k": 4,
        "primary_inertia": primary["inertia"],
        "primary_silhouette": primary_summary["primary_silhouette"],
        "cluster_sizes": primary_summary["cluster_sizes"], "random_state": 42,
        "n_init": int(contract["kmeans"]["n_init"]), "max_iter": int(contract["kmeans"]["max_iter"]),
        "tol": float(contract["kmeans"]["tol"]), "algorithm": contract["kmeans"]["algorithm"],
        "assignment_fingerprint": primary["assignment_fingerprint"],
        "output_sha256": {"partition": sha256_file(args.partition_output), "summary": sha256_file(args.summary_output)},
        "output_bytes": {"partition": args.partition_output.stat().st_size, "summary": args.summary_output.stat().st_size},
        "runtime_seconds": {"elbow_total": elbow_runtime, "silhouette_total": silhouette_runtime,
                            "primary_k4": primary["runtime_seconds"], "primary_k4_repeat": repeat["runtime_seconds"],
                            "sensitivity_total": sensitivity_runtime, "whole_run": time.perf_counter() - started},
        "peak_working_set_bytes": peak_working_set_bytes(), "validation": validation,
        "validation_status": "passed",
    }
    write_json(args.receipt, receipt)
    return receipt


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=root / "config/kmeans_contract.yaml")
    parser.add_argument("--node-metrics", type=Path, default=root / "data/processed/network/core_2023_2024/node_metrics.parquet")
    parser.add_argument("--partition-output", type=Path, default=root / "data/processed/network/core_2023_2024/kmeans_k4_partition.parquet")
    parser.add_argument("--summary-output", type=Path, default=root / "data/processed/network/core_2023_2024/kmeans_k4_summary.parquet")
    parser.add_argument("--elbow-csv", type=Path, default=root / "notes/kmeans-elbow.csv")
    parser.add_argument("--summary-csv", type=Path, default=root / "notes/kmeans-cluster-summary.csv")
    parser.add_argument("--primary-summary", type=Path, default=root / "notes/kmeans-primary-summary.json")
    parser.add_argument("--sensitivity-output", type=Path, default=root / "notes/kmeans-sensitivity-summary.json")
    parser.add_argument("--receipt", type=Path, default=root / "notes/kmeans-run-receipt.json")
    receipt = run(parser.parse_args())
    print(json.dumps({"status": receipt["validation_status"], "detected_knee": receipt["detected_knee"],
                      "silhouette_best_k": receipt["silhouette_best_k"]}))


if __name__ == "__main__":
    main()
