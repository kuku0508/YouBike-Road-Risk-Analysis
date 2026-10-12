"""Execute Phase 7.4 full hierarchical reconstruction from locked 72-feature matrices."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import time
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import scipy
from scipy.cluster.hierarchy import cophenet, dendrogram, fcluster, leaves_list, linkage
from scipy.spatial.distance import pdist
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score
from sklearn.preprocessing import StandardScaler

from profile_od_eligibility import sha256_file
from validate_hierarchical_contract import deterministic_relabel, expected_feature_columns

PIPELINE_VERSION = "hierarchical-reconstruction-v1"
INPUT_HASHES = {
    "weekday": "ed00378e3ce489b7c80bbc9a7a22198dffa7dc1c6b9bbd18804074963d987054",
    "holiday": "b232620f2ee14ff436439c715efaf89794e9ddbf7af8c8323f0814e44a2685d8",
}
CUTS = {"weekday": 5, "holiday": 4}
METRICS = ("betweenness", "eigenvector", "pagerank")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def array_hash(value: np.ndarray, dtype: str = "<f8") -> str:
    return hashlib.sha256(np.asarray(value, dtype=dtype).tobytes()).hexdigest()


def text_hash(values: list[str]) -> str:
    return hashlib.sha256("\n".join(values).encode("utf-8")).hexdigest()


def repository_path(path: Path) -> str:
    root = Path(__file__).resolve().parents[1]
    return str(path.resolve().relative_to(root)).replace("\\", "/")


def peak_memory() -> int | None:
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


def load_input(path: Path, day_type: str) -> tuple[pd.DataFrame, list[str], np.ndarray, dict[str, Any]]:
    observed_hash = sha256_file(path)
    if observed_hash != INPUT_HASHES[day_type]:
        raise RuntimeError(f"{day_type} input SHA-256 mismatch")
    frame = pq.ParquetFile(path).read().to_pandas()
    features = expected_feature_columns()
    if list(frame.columns) != ["station_id", "station_name", "city", *features]:
        raise RuntimeError(f"{day_type} exact feature/metadata schema mismatch")
    if len(frame) != 2782 or frame.station_id.isna().any() or frame.station_id.duplicated().any():
        raise RuntimeError(f"{day_type} station universe gate failed")
    ordered = frame.assign(station_id=frame.station_id.astype(str)).sort_values("station_id", kind="mergesort").reset_index(drop=True)
    if not ordered.station_id.equals(frame.station_id.astype(str).reset_index(drop=True)):
        raise RuntimeError(f"{day_type} source station ordering is not ascending")
    matrix = ordered[features].to_numpy(dtype=float)
    if matrix.shape != (2782, 72) or not np.isfinite(matrix).all():
        raise RuntimeError(f"{day_type} matrix contains invalid values")
    evidence = {"input_sha256": observed_hash, "station_count": len(ordered), "feature_count": len(features),
                "station_order_sha256": text_hash(ordered.station_id.tolist()),
                "feature_columns_sha256": text_hash(features), "no_nan": True, "all_finite": True}
    return ordered, features, matrix, evidence


def relabel(raw: np.ndarray, stations: list[str]) -> np.ndarray:
    return deterministic_relabel(raw, stations)


def validate_linkage(z: np.ndarray, n: int) -> dict[str, Any]:
    checks = {"shape": list(z.shape) == [n - 1, 4], "all_finite": bool(np.isfinite(z).all()),
              "distances_monotonic": bool(np.all(np.diff(z[:, 2]) >= -1e-12)),
              "final_merge_count": int(round(float(z[-1, 3]))) == n}
    if not all(checks.values()): raise RuntimeError(f"linkage validation failed: {checks}")
    return checks


def partition_summary(frame: pd.DataFrame, raw: np.ndarray, scaled: np.ndarray, day_type: str,
                      features: list[str]) -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, Any]]]:
    stations = frame.station_id.tolist(); labels = relabel(raw, stations); k = CUTS[day_type]
    if sorted(np.unique(labels).tolist()) != list(range(1, k + 1)):
        raise RuntimeError("cluster labels are not contiguous")
    assignment = frame[["station_id", "station_name", "city"]].copy()
    assignment[f"{day_type}_cluster_id"] = labels
    profile_rows = []; summaries = []
    raw_values = frame[features]
    for cluster_id in range(1, k + 1):
        mask = labels == cluster_id; indices = np.flatnonzero(mask); subset = raw_values.iloc[indices]
        centroid = scaled[indices].mean(axis=0)
        distances = np.linalg.norm(scaled[indices] - centroid, axis=1)
        prototype_idx = indices[int(np.argmin(distances))]
        leaders = {}
        for metric in METRICS:
            cols = [f"{metric}_h{hour:02d}" for hour in range(24)]
            aggregate = raw_values[cols].sum(axis=1)
            leader_idx = int(aggregate.iloc[indices].idxmax())
            leaders[metric] = {"station_id": str(frame.loc[leader_idx, "station_id"]),
                               "station_name": str(frame.loc[leader_idx, "station_name"]),
                               "aggregate_24h": float(aggregate.loc[leader_idx])}
            for hour, column in enumerate(cols):
                values = subset[column]
                profile_rows.append({"day_type": day_type, "cluster_id": cluster_id, "metric": metric,
                    "hour": hour, "mean": float(values.mean()), "median": float(values.median()),
                    "p25": float(values.quantile(.25)), "p75": float(values.quantile(.75))})
        summaries.append({"cluster_id": cluster_id, "node_count": int(mask.sum()),
            "percentage": float(mask.mean()), "prototype_station_id": str(frame.loc[prototype_idx, "station_id"]),
            "prototype_station_name": str(frame.loc[prototype_idx, "station_name"]),
            "prototype_distance_to_standardized_centroid": float(distances.min()), "leaders": leaders})
    return assignment, pd.DataFrame(profile_rows), summaries


def draw_dendrogram(z: np.ndarray, day_type: str, k: int, path: Path) -> float:
    started = time.perf_counter()
    fig, ax = plt.subplots(figsize=(18, 9), dpi=160)
    dendrogram(z, no_labels=True, color_threshold=0, above_threshold_color="#315A7D", ax=ax)
    label = "Weekday" if day_type == "weekday" else "Holiday"
    ax.set_title(f"{label} Full Dendrogram — 2023–2024 Reconstruction Variant", fontsize=16, pad=16)
    ax.text(.5, 1.01, f"Standardized 72-feature input · Euclidean · Ward.D2 reconstruction · report-reference cut k={k}",
            transform=ax.transAxes, ha="center", va="bottom", fontsize=10, color="#555555")
    ax.set_xlabel("All 2,782 stations (leaf labels hidden)"); ax.set_ylabel("Ward merge distance")
    ax.grid(axis="y", color="#D9DEE3", linewidth=.6, alpha=.7)
    for side in ("top", "right"): ax.spines[side].set_visible(False)
    fig.tight_layout(); path.parent.mkdir(parents=True, exist_ok=True); fig.savefig(path, bbox_inches="tight")
    plt.close(fig); return time.perf_counter() - started


def execute_day(day_type: str, frame: pd.DataFrame, features: list[str], matrix: np.ndarray,
                evidence: dict[str, Any], output_root: Path, figure_root: Path) -> tuple[dict[str, Any], np.ndarray]:
    total_started = time.perf_counter(); stations = frame.station_id.tolist(); k = CUTS[day_type]
    t = time.perf_counter(); scaler = StandardScaler(with_mean=True, with_std=True); scaled = scaler.fit_transform(matrix)
    scaler_runtime = time.perf_counter() - t
    scaler_hash = hashlib.sha256(np.concatenate([scaler.mean_, scaler.scale_]).astype("<f8").tobytes()).hexdigest()
    t = time.perf_counter(); distances = pdist(scaled, metric="euclidean"); z = linkage(distances, method="ward")
    primary_runtime = time.perf_counter() - t; validation = validate_linkage(z, len(frame))
    raw = fcluster(z, t=k, criterion="maxclust"); labels = relabel(raw, stations)
    leaf = leaves_list(z); leaf_stations = [stations[int(i)] for i in leaf]
    coph = float(cophenet(z, distances)[0])
    assignment, profiles, summaries = partition_summary(frame, raw, scaled, day_type, features)
    partition_path = output_root / f"hierarchical_{day_type}_partition.parquet"
    linkage_path = output_root / f"hierarchical_{day_type}_linkage.npy"
    leaf_path = output_root / f"hierarchical_{day_type}_leaf_order.json"
    pq.write_table(pa.Table.from_pandas(assignment, preserve_index=False), partition_path, compression="zstd")
    np.save(linkage_path, z, allow_pickle=False); write_json(leaf_path, {"day_type": day_type, "station_ids": leaf_stations})
    figure_path = figure_root / f"hierarchical_{day_type}_dendrogram.png"
    dendrogram_runtime = draw_dendrogram(z, day_type, k, figure_path)
    sensitivity = []
    t = time.perf_counter()
    for name, method, values, distances_for_coph in [
        ("standard_scaler_complete", "complete", scaled, distances),
        ("standard_scaler_average", "average", scaled, distances),
        ("no_scaling_ward", "ward", matrix, None),
    ]:
        d = distances_for_coph if distances_for_coph is not None else pdist(values, metric="euclidean")
        variant_z = linkage(d, method=method); validate_linkage(variant_z, len(frame))
        variant_labels = relabel(fcluster(variant_z, t=k, criterion="maxclust"), stations)
        sensitivity.append({"variant": name, "linkage": method, "scaling": name != "no_scaling_ward",
            "ari_vs_primary": float(adjusted_rand_score(labels, variant_labels)),
            "nmi_vs_primary": float(normalized_mutual_info_score(labels, variant_labels)),
            "cluster_sizes": {str(i): int((variant_labels == i).sum()) for i in range(1, k + 1)},
            "cophenetic_correlation": float(cophenet(variant_z, d)[0]),
            "linkage_sha256": array_hash(variant_z)})
    sensitivity_runtime = time.perf_counter() - t
    size_values = [item["node_count"] for item in summaries]
    receipt = {"day_type": day_type, **evidence, "cut_k": k, "cut_function": "scipy.cluster.hierarchy.fcluster(maxclust)",
        "scaler": {"class": "StandardScaler", "with_mean": True, "with_std": True,
                   "parameters_sha256": scaler_hash, "means": scaler.mean_.tolist(), "scales": scaler.scale_.tolist()},
        "distance": "euclidean", "linkage": "ward", "report_term": "Ward.D2",
        "linkage_shape": list(z.shape), "linkage_sha256": array_hash(z), "linkage_validation": validation,
        "leaf_order_sha256": text_hash(leaf_stations), "leaf_count": len(leaf_stations),
        "assignment_sha256": sha256_file(partition_path), "assignment_label_sha256": array_hash(labels, "<i8"),
        "cophenetic_correlation": coph, "cluster_sizes": {str(i["cluster_id"]): i["node_count"] for i in summaries},
        "cluster_size_statistics": {"min": min(size_values), "median": float(np.median(size_values)),
                                    "mean": float(np.mean(size_values)), "max": max(size_values)},
        "cluster_summaries": summaries, "sensitivity": sensitivity,
        "artifacts": {"partition": repository_path(partition_path), "linkage": repository_path(linkage_path),
                      "leaf_order": repository_path(leaf_path), "dendrogram": repository_path(figure_path)},
        "runtimes_seconds": {"standard_scaler": scaler_runtime, "pairwise_plus_primary_linkage": primary_runtime,
                             "dendrogram_generation": dendrogram_runtime, "sensitivity": sensitivity_runtime,
                             "total": time.perf_counter() - total_started}}
    return {"receipt": receipt, "assignment": assignment, "profiles": profiles, "labels": labels,
            "linkage": z, "leaf": leaf_stations}, scaled


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter(); args.output_root.mkdir(parents=True, exist_ok=True)
    data = {}
    for day_type, path in (("weekday", args.weekday_input), ("holiday", args.holiday_input)):
        frame, features, matrix, evidence = load_input(path, day_type)
        data[day_type] = execute_day(day_type, frame, features, matrix, evidence, args.output_root, args.figure_root)[0]
    if data["weekday"]["receipt"]["station_order_sha256"] != data["holiday"]["receipt"]["station_order_sha256"]:
        raise RuntimeError("weekday and holiday station universes/order differ")
    weekday_labels = data["weekday"]["labels"]; holiday_labels = data["holiday"]["labels"]
    comparison = {"ari": float(adjusted_rand_score(weekday_labels, holiday_labels)),
                  "nmi": float(normalized_mutual_info_score(weekday_labels, holiday_labels)),
                  "cross_tab": pd.crosstab(weekday_labels, holiday_labels).to_dict()}
    # Equivalent deterministic verification from the same immutable inputs.
    reproducibility = {}
    for day_type in ("weekday", "holiday"):
        frame, _, matrix, _ = load_input(args.weekday_input if day_type == "weekday" else args.holiday_input, day_type)
        scaled = StandardScaler().fit_transform(matrix); d = pdist(scaled); z2 = linkage(d, method="ward")
        labels2 = relabel(fcluster(z2, CUTS[day_type], criterion="maxclust"), frame.station_id.tolist())
        reproducibility[day_type] = {"linkage_hash_identical": array_hash(z2) == data[day_type]["receipt"]["linkage_sha256"],
            "leaf_order_hash_identical": text_hash([frame.station_id.iloc[int(i)] for i in leaves_list(z2)]) == data[day_type]["receipt"]["leaf_order_sha256"],
            "assignment_hash_identical": array_hash(labels2, "<i8") == data[day_type]["receipt"]["assignment_label_sha256"]}
    for day_type in ("weekday", "holiday"):
        data[day_type]["profiles"].to_csv(args.notes_root / f"hierarchical-{day_type}-summary.csv", index=False, encoding="utf-8-sig")
    sensitivity = {day: data[day]["receipt"]["sensitivity"] for day in ("weekday", "holiday")}
    sensitivity["weekday_vs_holiday"] = comparison
    write_json(args.sensitivity_output, sensitivity)
    receipt = {"contract_version": PIPELINE_VERSION, "reconstruction_period": "2023-2024",
        "period_caveat": "report text states 2022-2024; this is the analyst-selected 2023-2024 reconstruction variant",
        "scipy_version": scipy.__version__, "station_count": 2782, "feature_count": 72,
        "primary": {day: data[day]["receipt"] for day in ("weekday", "holiday")},
        "weekday_vs_holiday": comparison, "reproducibility": reproducibility,
        "peak_working_set_bytes": peak_memory(), "total_runtime_seconds": time.perf_counter() - started,
        "validation_status": "passed", "hierarchical_reconstruction_complete": True,
        "brouter_triggered": False, "accident_stage_triggered": False}
    if not all(all(item.values()) for item in reproducibility.values()): raise RuntimeError("deterministic verification failed")
    write_json(args.receipt, receipt); return receipt


def main() -> None:
    root = Path(__file__).resolve().parents[1]; parser = argparse.ArgumentParser()
    base = root / "data/processed/network/hourly_2023_2024"
    parser.add_argument("--weekday-input", type=Path, default=base / "hierarchical_weekday_72_features.parquet")
    parser.add_argument("--holiday-input", type=Path, default=base / "hierarchical_holiday_72_features.parquet")
    parser.add_argument("--output-root", type=Path, default=base)
    parser.add_argument("--figure-root", type=Path, default=root / "reports/figures")
    parser.add_argument("--notes-root", type=Path, default=root / "notes")
    parser.add_argument("--receipt", type=Path, default=root / "notes/hierarchical-run-receipt.json")
    parser.add_argument("--sensitivity-output", type=Path, default=root / "notes/hierarchical-sensitivity-summary.json")
    result = run(parser.parse_args()); print(json.dumps({"status": result["validation_status"],
        "runtime_seconds": result["total_runtime_seconds"]}))


if __name__ == "__main__": main()
