"""Build a georeferenced presentation overlay from validated segment exposure.

This is a raster visualization of existing weights. It does not route trips,
aggregate new study units, or calculate any risk measure.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from pyproj import Transformer
import pyarrow.parquet as pq


SOURCE = Path("data/processed/routing/direction_neutral_segment_exposure_2023_2024.parquet")
OUTPUT = Path("figures/routing-flow-overlay-2023-2024.png")
MANIFEST = Path("figures/routing-flow-overlay-2023-2024.json")
EXPECTED_SHA256 = "c6dd301a7b328d650aa4e58a7e9b36330d6389465594ad69010d39c02dd0cd6f"
EXPECTED_ROWS = 106_049
EXPECTED_WEIGHTED_TRAVERSALS = 4_674_227_848
WIDTH, HEIGHT = 3200, 2600
COLORS = (
    (72, 124, 169, 150),   # 1–9
    (42, 119, 169, 175),   # 10–99
    (31, 111, 151, 190),   # 100–999
    (216, 138, 54, 205),   # 1,000–9,999
    (220, 90, 51, 220),    # 10,000–99,999
    (158, 36, 63, 235),    # 100,000+
)


def main() -> None:
    digest = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    if digest != EXPECTED_SHA256:
        raise ValueError(f"Source SHA-256 mismatch: {digest}")
    names = [
        "endpoint1_lon_e6", "endpoint1_lat_e6", "endpoint2_lon_e6", "endpoint2_lat_e6",
        "bidirectional_total_trip_weight",
    ]
    table = pq.read_table(SOURCE, columns=names)
    if len(table) != EXPECTED_ROWS:
        raise ValueError(f"Unexpected segment count: {len(table)}")
    weights = table[names[4]].to_numpy()
    if int(weights.sum()) != EXPECTED_WEIGHTED_TRAVERSALS or np.any(weights <= 0):
        raise ValueError("Weighted traversal conservation failed")
    lon1, lat1, lon2, lat2 = [table[n].to_numpy() / 1_000_000 for n in names[:4]]
    project = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    inverse = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
    x1, y1 = project.transform(lon1, lat1)
    x2, y2 = project.transform(lon2, lat2)
    min_x = float(min(x1.min(), x2.min()) - 1000)
    max_x = float(max(x1.max(), x2.max()) + 1000)
    min_y = float(min(y1.min(), y2.min()) - 1000)
    max_y = float(max(y1.max(), y2.max()) + 1000)
    # ImageOverlay stretches linearly in Web Mercator, matching these pixel coordinates.
    px1 = np.rint((x1 - min_x) * (WIDTH - 1) / (max_x - min_x)).astype(int)
    px2 = np.rint((x2 - min_x) * (WIDTH - 1) / (max_x - min_x)).astype(int)
    py1 = np.rint((max_y - y1) * (HEIGHT - 1) / (max_y - min_y)).astype(int)
    py2 = np.rint((max_y - y2) * (HEIGHT - 1) / (max_y - min_y)).astype(int)
    bins = np.searchsorted([10, 100, 1_000, 10_000, 100_000], weights, side="right")
    image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image, "RGBA")
    for level in range(len(COLORS)):
        for i in np.flatnonzero(bins == level):
            draw.line((int(px1[i]), int(py1[i]), int(px2[i]), int(py2[i])), fill=COLORS[level], width=3)
    west, south = inverse.transform(min_x, min_y)
    east, north = inverse.transform(max_x, max_y)
    if not (west < east and south < north):
        raise ValueError("Invalid geographic bounds")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUTPUT, optimize=True)
    receipt = {
        "source_sha256": digest,
        "source_rows": len(table),
        "weighted_traversals": int(weights.sum()),
        "output_sha256": hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),
        "image_width": WIDTH,
        "image_height": HEIGHT,
        "bounds": [[south, west], [north, east]],
        "crs": "EPSG:3857 raster aligned to Leaflet ImageOverlay bounds",
        "display_bins": ["1–9", "10–99", "100–999", "1,000–9,999", "10,000–99,999", "100,000+"],
        "risk_measure": False,
    }
    MANIFEST.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    main()

