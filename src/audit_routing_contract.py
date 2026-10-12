"""Read-only Phase 8.0 OD and station-coordinate audit; no full routing."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_sources(historical: Path, taipei_current: Path, nt_current: Path):
    sources = defaultdict(list)
    with historical.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            sources[row["Station Number"]].append(("taipei_2024-05-31", float(row["Longitude"]), float(row["Latitude"])))
    for row in json.loads(taipei_current.read_text(encoding="utf-8-sig")):
        sources[str(row["sno"])].append(("taipei_2026-09-13", float(row["longitude"]), float(row["latitude"])))
    with nt_current.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            sources[row["sno"]].append(("new_taipei_2026-09-14", float(row["lng"]), float(row["lat"])))
    return sources


def haversine(a, b):
    lon1, lat1, lon2, lat2 = map(math.radians, (*a, *b))
    dlon, dlat = lon2 - lon1, lat2 - lat1
    x = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(x))


def choose_coordinate(entries):
    unique = {(round(lon, 7), round(lat, 7)) for _, lon, lat in entries}
    dated = [e for e in entries if e[0] == "taipei_2024-05-31"]
    if len(unique) > 1:
        return None, "coordinate_conflict"
    if dated:
        return (dated[0][1], dated[0][2]), "historical_snapshot"
    if entries:
        return (entries[0][1], entries[0][2]), "current_only_temporal_unresolved"
    return None, "missing_coordinate"


def deterministic_sample(od, coords):
    nonloop = od[od.origin_station_id != od.destination_station_id].copy()
    nonloop["pair"] = nonloop.origin_station_id + "->" + nonloop.destination_station_id
    available = nonloop[nonloop.origin_station_id.isin(coords) & nonloop.destination_station_id.isin(coords)].copy()
    available["distance_m"] = [haversine(coords[o], coords[d]) for o, d in zip(available.origin_station_id, available.destination_station_id)]
    reciprocal = set(available.pair) & {f"{d}->{o}" for o, d in zip(available.origin_station_id, available.destination_station_id)}
    selected = []
    def add(row, label):
        key = row.pair
        if key not in {x["pair"] for x in selected}:
            selected.append({"pair": key, "category": label, "trip_count": int(row.trip_count), "distance_m": float(row.distance_m)})
    for _, row in available.nlargest(3, "trip_count").iterrows(): add(row, "high_flow")
    for _, row in available.iloc[(available.trip_count.rank(method="first", pct=True)-.5).abs().nsmallest(3).index].iterrows(): add(row, "middle_flow")
    for _, row in available.sort_values(["trip_count", "pair"]).head(3).iterrows(): add(row, "low_flow")
    cross = available[available.destination_city == "New Taipei"]
    if len(cross): add(cross.sort_values(["trip_count", "pair"], ascending=[False, True]).iloc[0], "taipei_to_new_taipei")
    recip = available[available.pair.isin(reciprocal)].sort_values(["trip_count", "pair"], ascending=[False, True])
    if len(recip):
        first = recip.iloc[0]; add(first, "reciprocal")
        reverse = available[available.pair == f"{first.destination_station_id}->{first.origin_station_id}"]
        if len(reverse): add(reverse.iloc[0], "reciprocal")
    add(available.sort_values(["distance_m", "pair"]).iloc[0], "short_distance")
    add(available.sort_values(["distance_m", "pair"], ascending=[False, True]).iloc[0], "long_distance")
    for _, row in available.sort_values("pair").iterrows():
        if len(selected) >= 20: break
        add(row, "deterministic_fill")
    loop = od[od.origin_station_id == od.destination_station_id].sort_values(["trip_count", "origin_station_id"], ascending=[False, True]).iloc[0]
    selected.append({"pair": f"{loop.origin_station_id}->{loop.destination_station_id}", "category": "self_loop_exclusion", "trip_count": int(loop.trip_count), "distance_m": 0.0})
    return selected


def main(args):
    root = args.output.resolve().parents[1]
    rel = lambda path: path.resolve().relative_to(root).as_posix()
    od = pd.read_parquet(args.od)
    nodes = sorted(set(od.origin_station_id) | set(od.destination_station_id))
    source_rows = load_sources(args.historical, args.taipei_current, args.nt_current)
    statuses, coords, conflicts, node_status = Counter(), {}, [], {}
    coordinate_to_ids = defaultdict(list)
    for station_id in nodes:
        coordinate, status = choose_coordinate(source_rows.get(station_id, []))
        node_status[station_id] = status
        statuses[status] += 1
        if coordinate is not None:
            coords[station_id] = coordinate
            coordinate_to_ids[tuple(round(x, 7) for x in coordinate)].append(station_id)
        if status == "coordinate_conflict": conflicts.append(station_id)
    loops = od[od.origin_station_id == od.destination_station_id]
    impacts = {}
    nonself_mask = od.origin_station_id != od.destination_station_id
    for status in ("coordinate_conflict", "current_only_temporal_unresolved"):
        ids = {sid for sid, value in node_status.items() if value == status}
        mask = od.origin_station_id.isin(ids) | od.destination_station_id.isin(ids)
        impacts[status] = {"od_edges": int(mask.sum()), "trip_weight": int(od.loc[mask, "trip_count"].sum()),
                           "non_self_od_edges": int((mask & nonself_mask).sum()),
                           "non_self_trip_weight": int(od.loc[mask & nonself_mask, "trip_count"].sum())}
    unresolved_ids = {sid for sid, value in node_status.items() if value != "historical_snapshot"}
    unresolved_mask = od.origin_station_id.isin(unresolved_ids) | od.destination_station_id.isin(unresolved_ids)
    impacts["unresolved_union"] = {"od_edges": int(unresolved_mask.sum()),
        "trip_weight": int(od.loc[unresolved_mask, "trip_count"].sum()),
        "non_self_od_edges": int((unresolved_mask & nonself_mask).sum()),
        "non_self_trip_weight": int(od.loc[unresolved_mask & nonself_mask, "trip_count"].sum())}
    sample = deterministic_sample(od, coords)
    receipt = {
        "contract_version": "road-routing-contract-v1",
        "full_routing_executed": False,
        "od": {"path": rel(args.od), "sha256": sha256_file(args.od), "edge_count": int(len(od)),
               "trip_weight": int(od.trip_count.sum()), "node_count": len(nodes),
               "self_loop_edges": int(len(loops)), "self_loop_trip_weight": int(loops.trip_count.sum()),
               "eligible_non_self_edges": int(len(od)-len(loops)),
               "eligible_non_self_trip_weight": int(od.trip_count.sum()-loops.trip_count.sum())},
        "coordinate_sources": {
            "historical": {"path": rel(args.historical), "sha256": sha256_file(args.historical)},
            "taipei_current": {"path": rel(args.taipei_current), "sha256": sha256_file(args.taipei_current)},
            "new_taipei_current": {"path": rel(args.nt_current), "sha256": sha256_file(args.nt_current)}},
        "coordinate_audit": {"routing_nodes": len(nodes), "status_counts": dict(statuses),
            "usable_unique_coordinates_under_v1": len(coords), "conflicting_station_ids": conflicts,
            "duplicate_coordinate_groups": sum(len(v)>1 for v in coordinate_to_ids.values()),
            "duplicate_coordinate_station_count": sum(len(v) for v in coordinate_to_ids.values() if len(v)>1),
            "outside_expected_bounds": sum(not (120.9 <= lon <= 122.1 and 24.5 <= lat <= 25.5) for lon,lat in coords.values()),
            "od_impact_by_status": impacts},
        "bounded_sample": {"definition": sample,
            "sha256": hashlib.sha256(json.dumps(sample,sort_keys=True,separators=(",", ":")).encode()).hexdigest(),
            "routing_executed": False},
        "brouter_environment": {"status": "unresolved", "java_version": "25.0.4.1",
            "requested_brouter_version": "1.7.10", "profile_status": "not_locally_pinned",
            "routing_graph_status": "download_not_validated"},
        "validation_status": "blocked_brouter_environment_and_coordinates",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"status": receipt["validation_status"], "coordinate_audit": receipt["coordinate_audit"], "od": receipt["od"]}, ensure_ascii=False))


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--od", type=Path, default=root/"data/processed/od/aggregate/core_2023_2024/od.parquet")
    parser.add_argument("--historical", type=Path, default=root/"data/raw/station_snapshot_2024-05-31.csv")
    parser.add_argument("--taipei-current", type=Path, default=root/"data/raw/youbike_immediate_2026-09-13.json")
    parser.add_argument("--nt-current", type=Path, default=root/"data/raw/new_taipei_youbike_2026-09-14.csv")
    parser.add_argument("--output", type=Path, default=root/"notes/brouter-contract-validation.json")
    main(parser.parse_args())
