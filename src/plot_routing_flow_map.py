"""Render the validated 2023–2024 BRouter microsegment exposure as a map.

Presentation only: this script does not recompute routes, weights, or risk.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.colors import LogNorm
from matplotlib.ticker import FuncFormatter
import numpy as np
import pyarrow.parquet as pq


EXPECTED_SHA256 = "c6dd301a7b328d650aa4e58a7e9b36330d6389465594ad69010d39c02dd0cd6f"
EXPECTED_ROWS = 106_049
EXPECTED_WEIGHTED_TRAVERSALS = 4_674_227_848
SOURCE = Path("data/processed/routing/direction_neutral_segment_exposure_2023_2024.parquet")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=Path("figures/routing-flow-2023-2024.png"))
    args = parser.parse_args()

    digest = hashlib.sha256(args.source.read_bytes()).hexdigest()
    if digest != EXPECTED_SHA256:
        raise ValueError(f"Source SHA-256 mismatch: {digest}")

    columns = [
        "endpoint1_lon_e6", "endpoint1_lat_e6", "endpoint2_lon_e6", "endpoint2_lat_e6",
        "bidirectional_total_trip_weight",
    ]
    table = pq.read_table(args.source, columns=columns)
    if len(table) != EXPECTED_ROWS:
        raise ValueError(f"Unexpected segment count: {len(table)}")
    values = table["bidirectional_total_trip_weight"].to_numpy()
    if int(values.sum()) != EXPECTED_WEIGHTED_TRAVERSALS or np.any(values <= 0):
        raise ValueError("Weighted traversal conservation failed")

    coords = np.stack([table[c].to_numpy() for c in columns[:4]], axis=1) / 1_000_000
    segments = coords.reshape(-1, 2, 2)
    plt.rcParams.update({"font.family": ["Noto Sans TC", "Microsoft JhengHei", "sans-serif"]})
    fig, ax = plt.subplots(figsize=(14, 10), dpi=160)
    fig.patch.set_facecolor("#fafaf8")
    ax.set_facecolor("#fafaf8")
    collection = LineCollection(
        segments, cmap="YlOrRd", norm=LogNorm(vmin=1, vmax=float(values.max())),
        linewidths=0.85, alpha=0.88, rasterized=True,
    )
    collection.set_array(values)
    ax.add_collection(collection)
    ax.set_xlim(float(coords[:, [0, 2]].min()) - 0.015, float(coords[:, [0, 2]].max()) + 0.015)
    ax.set_ylim(float(coords[:, [1, 3]].min()) - 0.012, float(coords[:, [1, 3]].max()) + 0.012)
    ax.set_aspect(1 / np.cos(np.deg2rad(25.1)))
    ax.set_xlabel("經度（°E）", fontsize=11)
    ax.set_ylabel("緯度（°N）", fontsize=11)
    ax.grid(color="#d7dfe0", alpha=0.45, linewidth=0.45)
    for spine in ax.spines.values():
        spine.set_color("#ccd4d7")

    cb = fig.colorbar(collection, ax=ax, fraction=0.025, pad=0.025)
    cb.set_label("估計路段通過次數（對數色階）", fontsize=11)
    cb.set_ticks([1, 10, 100, 1_000, 10_000, 100_000, 1_000_000])
    cb.ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _pos: f"{x:,.0f}"))
    cb.ax.minorticks_off()
    fig.suptitle("2023–2024 YouBike 重建路徑的道路微路段通過量", fontsize=21, y=0.965)
    fig.text(0.51, 0.925, "106,049 個方向中立微路段｜顏色代表加權 traversal，線寬固定", ha="center", fontsize=11, color="#405463")
    fig.text(0.5, 0.045, "BRouter 模擬路徑 × 旅次權重；並非 GPS 實測車流，也不代表事故風險。", ha="center", fontsize=10, color="#536773")
    fig.subplots_adjust(left=0.085, right=0.89, top=0.89, bottom=0.105)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=160, facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"source_sha256={digest}")
    print(f"segments={len(table)} weighted_traversals={int(values.sum())}")
    print(f"output={args.output} sha256={hashlib.sha256(args.output.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()

