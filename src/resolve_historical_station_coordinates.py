"""Resolve historical station coordinates without routing or name-based joins.

Phase 8.0A is deliberately conservative: evidence is joined only by exact
station ID, every source row is retained, and current-only coordinates never
become accepted historical coordinates.
"""
from __future__ import annotations

import argparse
import calendar
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

import pandas as pd


LEDGER_COLUMNS = [
    "station_id", "station_name", "city", "latitude", "longitude",
    "source_name", "source_url_or_reference", "source_date", "snapshot_date",
    "valid_from", "valid_to", "source_type", "official_status",
    "retrieval_date", "source_hash", "evidence_notes",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def dataframe_fingerprint(frame: pd.DataFrame, columns: list[str]) -> str:
    ordered = frame[columns].fillna("").astype(str).sort_values(columns, kind="mergesort")
    payload = ordered.to_csv(index=False, lineterminator="\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, (*a, *b))
    dlon, dlat = lon2 - lon1, lat2 - lat1
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(value))


def displacement_bin(distance_m: float) -> str:
    if distance_m == 0:
        return "exact_same"
    if distance_m < 5:
        return "lt_5m"
    if distance_m < 15:
        return "5_15m"
    if distance_m < 30:
        return "15_30m"
    if distance_m < 100:
        return "30_100m"
    return "gte_100m"


def month_bounds(value: str) -> tuple[str, str]:
    year, month = map(int, value.replace("/", "-").split("-")[:2])
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"


def observed_periods(monthly_dir: Path) -> pd.DataFrame:
    monthly_nodes: list[pd.DataFrame] = []
    for path in sorted(monthly_dir.glob("year=*/month=*/od.parquet")):
        year = int(path.parent.parent.name.split("=")[1])
        month = int(path.parent.name.split("=")[1])
        if not (2023 <= year <= 2024):
            continue
        frame = pd.read_parquet(path, columns=[
            "origin_station_id", "destination_station_id", "origin_station_name",
            "destination_station_name", "origin_city", "destination_city",
        ])
        stamp = f"{year:04d}-{month:02d}"
        for side in ("origin", "destination"):
            part = frame[[f"{side}_station_id", f"{side}_station_name", f"{side}_city"]].copy()
            part.columns = ["station_id", "station_name", "city"]
            part["station_id"] = part.station_id.astype(str)
            part["observed_month"] = stamp
            monthly_nodes.append(part.drop_duplicates("station_id"))
    combined = pd.concat(monthly_nodes, ignore_index=True)
    span = combined.groupby("station_id", as_index=False).agg(
        first_observed_month=("observed_month", "min"), last_observed_month=("observed_month", "max"))
    identity = combined.sort_values(["observed_month", "station_id"]).drop_duplicates("station_id", keep="last")
    out = span.merge(identity[["station_id", "station_name", "city"]], on="station_id", how="left")
    out = out[["station_id", "station_name", "city", "first_observed_month", "last_observed_month"]].sort_values("station_id").reset_index(drop=True)
    bounds = out.apply(lambda row: (*month_bounds(row.first_observed_month)[0:1], month_bounds(row.last_observed_month)[1]), axis=1)
    out[["first_observed_date", "last_observed_date"]] = pd.DataFrame(bounds.tolist(), index=out.index)
    return out


def load_evidence(historical: Path, taipei_current: Path, nt_current: Path) -> pd.DataFrame:
    retrieval = "2026-09-19"
    rows: list[dict] = []
    historical_hash = sha256_file(historical)
    with historical.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            rows.append({
                "station_id": str(row["Station Number"]), "station_name": row["Station"], "city": "Taipei",
                "latitude": float(row["Latitude"]), "longitude": float(row["Longitude"]),
                "source_name": "preserved_taipei_official_feed_capture_2024-05-31",
                "source_url_or_reference": "https://github.com/LittleFish-Coder/youbike-info-collector/blob/master/result/2024-05-31.csv",
                "source_date": "2024-05-31", "snapshot_date": "2024-05-31",
                "valid_from": None, "valid_to": None, "source_type": "dated_official_feed_capture",
                "official_status": "secondary_archive_of_official_endpoint", "retrieval_date": retrieval,
                "source_hash": historical_hash,
                "evidence_notes": "Dated capture of the Taipei official real-time feed; archive host is third-party and supplies no validity interval.",
            })
    taipei_hash = sha256_file(taipei_current)
    for row in json.loads(taipei_current.read_text(encoding="utf-8-sig")):
        rows.append({
            "station_id": str(row["sno"]), "station_name": str(row["sna"]).removeprefix("YouBike2.0_"), "city": "Taipei",
            "latitude": float(row["latitude"]), "longitude": float(row["longitude"]),
            "source_name": "taipei_official_current_2026-09-13",
            "source_url_or_reference": "https://tcgbusfs.blob.core.windows.net/dotapp/youbike/v2/youbike_immediate.json",
            "source_date": "2026-09-13", "snapshot_date": "2026-09-13", "valid_from": None, "valid_to": None,
            "source_type": "official_current_endpoint_snapshot", "official_status": "official",
            "retrieval_date": retrieval, "source_hash": taipei_hash,
            "evidence_notes": "Current evidence only; not proof of a 2023-2024 location.",
        })
    nt_hash = sha256_file(nt_current)
    with nt_current.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            rows.append({
                "station_id": str(row["sno"]), "station_name": str(row["sna"]).removeprefix("YouBike2.0_"), "city": "New Taipei",
                "latitude": float(row["lat"]), "longitude": float(row["lng"]),
                "source_name": "new_taipei_official_current_2026-09-14",
                "source_url_or_reference": "https://data.ntpc.gov.tw/api/datasets/010e5b15-3823-4b20-b401-b1cf000550c5/csv",
                "source_date": "2026-09-14", "snapshot_date": "2026-09-14", "valid_from": None, "valid_to": None,
                "source_type": "official_current_endpoint_snapshot", "official_status": "official",
                "retrieval_date": retrieval, "source_hash": nt_hash,
                "evidence_notes": "Current evidence only; not proof of a 2023-2024 location.",
            })
    return pd.DataFrame(rows, columns=LEDGER_COLUMNS).sort_values(["station_id", "snapshot_date", "source_name"]).reset_index(drop=True)


def classify_station(group: pd.DataFrame, observed: pd.Series) -> dict:
    historical = group[group.snapshot_date == "2024-05-31"]
    current = group[group.snapshot_date.str.startswith("2026-")]
    evidence_name = group.sort_values("snapshot_date").iloc[-1].station_name if len(group) else observed.station_name
    evidence_city = group.sort_values("snapshot_date").iloc[-1].city if len(group) else observed.city
    result = {
        "station_id": observed.station_id, "station_name": evidence_name, "city": evidence_city,
        "first_observed_date": observed.first_observed_date, "last_observed_date": observed.last_observed_date,
        "routing_lat": None, "routing_lon": None, "evidence_tier": "unaccepted",
        "evidence_source_count": int(len(group)), "earliest_support_date": group.snapshot_date.min() if len(group) else None,
        "latest_support_date": group.snapshot_date.max() if len(group) else None,
        "coordinate_status": "uncovered", "accepted": False, "reason_unresolved": "no_evidence",
    }
    if historical.empty:
        result["reason_unresolved"] = "current_only_without_temporal_support" if len(current) else "no_coordinate_source"
        return result
    old = (float(historical.iloc[0].longitude), float(historical.iloc[0].latitude))
    if len(current):
        new = (float(current.iloc[0].longitude), float(current.iloc[0].latitude))
        distance = haversine_m(old, new)
        if distance > 0.01:
            result.update({"coordinate_status": "unresolved_conflict", "reason_unresolved": "2024_2026_coordinate_conflict",
                           "displacement_m": distance})
            return result
        # A pre-observation dated capture plus a post-period official snapshot brackets
        # stations first observed after the capture. This is inference, not direct fact.
        if observed.first_observed_date >= "2024-06-01":
            result.update({"routing_lon": old[0], "routing_lat": old[1], "evidence_tier": "tier_2_temporally_bracketed_stable",
                           "coordinate_status": "fully_covered", "accepted": True, "reason_unresolved": None,
                           "displacement_m": distance})
            return result
        result.update({"routing_lon": old[0], "routing_lat": old[1], "evidence_tier": "tier_3_single_sided_temporal_support",
                       "coordinate_status": "partially_covered", "reason_unresolved": "evidence_does_not_cover_pre_snapshot_observations",
                       "displacement_m": distance})
        return result
    result.update({"routing_lon": old[0], "routing_lat": old[1], "evidence_tier": "tier_3_single_sided_temporal_support",
                   "coordinate_status": "partially_covered", "reason_unresolved": "single_historical_snapshot_without_bracketing"})
    return result


def impact_table(od: pd.DataFrame, unresolved: pd.DataFrame) -> pd.DataFrame:
    nonself = od[od.origin_station_id != od.destination_station_id].copy()
    rows = []
    for row in unresolved.itertuples():
        mask = (nonself.origin_station_id == row.station_id) | (nonself.destination_station_id == row.station_id)
        subset = nonself.loc[mask]
        counterparts = set(subset.origin_station_id) | set(subset.destination_station_id)
        counterparts.discard(row.station_id)
        rows.append({**row._asdict(), "affected_non_self_od_edges": int(len(subset)),
                     "affected_non_self_trip_weight": int(subset.trip_count.sum()),
                     "counterpart_station_count": len(counterparts)})
    return pd.DataFrame(rows).sort_values(["affected_non_self_trip_weight", "affected_non_self_od_edges", "station_id"], ascending=[False, False, True])


def resolve(args) -> dict:
    root = args.root.resolve()
    observed = observed_periods(args.monthly_od)
    evidence = load_evidence(args.historical, args.taipei_current, args.nt_current)
    core_ids = set(observed.station_id)
    evidence = evidence[evidence.station_id.isin(core_ids)].reset_index(drop=True)
    grouped = {station_id: frame for station_id, frame in evidence.groupby("station_id")}
    resolution = pd.DataFrame([classify_station(grouped.get(row.station_id, evidence.iloc[0:0]), row) for _, row in observed.iterrows()])
    accepted = resolution[resolution.accepted].copy()
    accepted = accepted[["station_id", "station_name", "city", "routing_lat", "routing_lon", "evidence_tier",
                         "evidence_source_count", "earliest_support_date", "latest_support_date", "coordinate_status"]]
    unresolved = resolution[~resolution.accepted].copy()
    od = pd.read_parquet(args.od)
    unresolved_impact = impact_table(od, unresolved)
    nonself = od[od.origin_station_id != od.destination_station_id]
    accepted_ids = set(accepted.station_id)
    route_mask = nonself.origin_station_id.isin(accepted_ids) & nonself.destination_station_id.isin(accepted_ids)

    conflicts = []
    for station_id, group in evidence.groupby("station_id"):
        if set(group.snapshot_date) >= {"2024-05-31", "2026-09-13"}:
            old = group[group.snapshot_date == "2024-05-31"].iloc[0]
            new = group[group.snapshot_date == "2026-09-13"].iloc[0]
            distance = haversine_m((old.longitude, old.latitude), (new.longitude, new.latitude))
            if distance > 0.01:
                conflicts.append({"station_id": station_id, "station_name_2024": old.station_name,
                                  "station_name_2026": new.station_name, "city": "Taipei",
                                  "latitude_2024": old.latitude, "longitude_2024": old.longitude,
                                  "latitude_2026": new.latitude, "longitude_2026": new.longitude,
                                  "distance_m": distance, "distance_bin": displacement_bin(distance),
                                  "final_resolution": "unresolved_conflict",
                                  "reason": "Two snapshots do not locate the change date relative to 2023-2024."})
    conflicts_df = pd.DataFrame(conflicts).sort_values("distance_m", ascending=False)

    args.interim.mkdir(parents=True, exist_ok=True)
    args.processed.mkdir(parents=True, exist_ok=True)
    evidence_path = args.interim / "station_coordinate_evidence.parquet"
    accepted_path = args.processed / "routing_station_coordinates_2023_2024.parquet"
    unresolved_path = args.processed / "routing_coordinate_unresolved.parquet"
    conflict_path = args.interim / "routing_coordinate_conflicts.parquet"
    evidence.to_parquet(evidence_path, index=False)
    accepted.to_parquet(accepted_path, index=False)
    unresolved_impact.to_parquet(unresolved_path, index=False)
    conflicts_df.to_parquet(conflict_path, index=False)

    status_counts = Counter(resolution.coordinate_status)
    city_summary = {}
    for city, frame in resolution.groupby("city"):
        city_summary[city] = {"nodes": int(len(frame)), "accepted_nodes": int(frame.accepted.sum()),
                              "unresolved_nodes": int((~frame.accepted).sum())}
    displacement = conflicts_df.distance_m if len(conflicts_df) else pd.Series(dtype=float)
    receipt = {
        "phase": "8.0A", "policy_version": "historical-coordinate-resolution-policy-v1",
        "research_period": "2023-01-01/2024-12-31", "full_routing_executed": False,
        "initial_coordinate_status": {"routing_nodes": 2782, "dated_2024_05_31": 1384,
                                      "coordinate_conflicts": 31, "current_only": 1367},
        "historical_sources_used": [
            {"name": "preserved_taipei_official_feed_capture_2024-05-31", "sha256": sha256_file(args.historical)},
            {"name": "taipei_official_current_2026-09-13", "sha256": sha256_file(args.taipei_current)},
            {"name": "new_taipei_official_current_2026-09-14", "sha256": sha256_file(args.nt_current)},
        ],
        "source_discovery": {"official_historical_download_obtained": False,
                             "tdx_historical_api_discovered": True,
                             "tdx_access_status": "credentials_required_not_available",
                             "official_city_portals": "current endpoints only in discovered public listings"},
        "evidence_ledger": {"path": str(evidence_path.relative_to(root)).replace("\\", "/"), "rows": int(len(evidence)),
                            "sha256": sha256_file(evidence_path)},
        "resolution": {"direct_historical_resolved_count": 0,
                       "direct_historical_evidence_node_count": int(evidence.loc[evidence.snapshot_date == "2024-05-31", "station_id"].nunique()),
                       "temporally_bracketed_count": int((resolution.evidence_tier == "tier_2_temporally_bracketed_stable").sum()),
                       "single_sided_not_accepted": int((resolution.evidence_tier == "tier_3_single_sided_temporal_support").sum()),
                       "current_only_remaining": int((resolution.reason_unresolved == "current_only_without_temporal_support").sum()),
                       "conflicts_resolved": 0, "conflicts_unresolved": int(len(conflicts_df)),
                       "within_period_relocation_count": 0, "within_period_relocation_status": "not_established_with_available_evidence",
                       "coordinate_era_count": 0, "coordinate_status_counts": dict(status_counts),
                       "city_summary": city_summary},
        "conflict_displacement": {"count": int(len(displacement)),
                                  "bins": dict(Counter(conflicts_df.distance_bin)) if len(conflicts_df) else {},
                                  "p50_m": float(displacement.quantile(.5)) if len(displacement) else None,
                                  "p90_m": float(displacement.quantile(.9)) if len(displacement) else None,
                                  "p95_m": float(displacement.quantile(.95)) if len(displacement) else None,
                                  "max_m": float(displacement.max()) if len(displacement) else None},
        "routing_readiness": {"routing_ready_nodes": int(len(accepted)), "total_nodes": int(len(resolution)),
                              "node_coverage": float(len(accepted) / len(resolution)),
                              "routing_ready_non_self_od_edges": int(route_mask.sum()), "total_non_self_od_edges": int(len(nonself)),
                              "od_edge_coverage": float(route_mask.mean()),
                              "routing_ready_non_self_trip_weight": int(nonself.loc[route_mask, "trip_count"].sum()),
                              "total_non_self_trip_weight": int(nonself.trip_count.sum()),
                              "trip_weight_coverage": float(nonself.loc[route_mask, "trip_count"].sum() / nonself.trip_count.sum())},
        "artifacts": {
            "final_coordinate_artifact": {"path": str(accepted_path.relative_to(root)).replace("\\", "/"), "rows": int(len(accepted)), "sha256": sha256_file(accepted_path),
                                          "station_id_fingerprint": dataframe_fingerprint(accepted, ["station_id"]),
                                          "coordinate_fingerprint": dataframe_fingerprint(accepted, ["station_id", "routing_lat", "routing_lon"])},
            "unresolved_artifact": {"path": str(unresolved_path.relative_to(root)).replace("\\", "/"), "rows": int(len(unresolved_impact)), "sha256": sha256_file(unresolved_path)},
            "conflict_artifact": {"path": str(conflict_path.relative_to(root)).replace("\\", "/"), "rows": int(len(conflicts_df)), "sha256": sha256_file(conflict_path)},
        },
        "routing_contract_version": "road-routing-contract-v1", "routing_unit": "unique_directed_od_pair",
        "routing_unit_assessment": "No within-period relocation was established, but insufficient evidence prevents treating this as proof that none occurred.",
        "readiness_status": "HISTORICAL COORDINATES: PARTIALLY RESOLVED — ROAD ROUTING STILL BLOCKED",
    }
    return receipt


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--monthly-od", type=Path, default=root / "data/processed/od/monthly")
    parser.add_argument("--od", type=Path, default=root / "data/processed/od/aggregate/core_2023_2024/od.parquet")
    parser.add_argument("--historical", type=Path, default=root / "data/raw/station_snapshot_2024-05-31.csv")
    parser.add_argument("--taipei-current", type=Path, default=root / "data/raw/youbike_immediate_2026-09-13.json")
    parser.add_argument("--nt-current", type=Path, default=root / "data/raw/new_taipei_youbike_2026-09-14.csv")
    parser.add_argument("--interim", type=Path, default=root / "data/interim/routing")
    parser.add_argument("--processed", type=Path, default=root / "data/processed/routing")
    parser.add_argument("--receipt", type=Path, default=root / "notes/historical-coordinate-resolution-receipt.json")
    args = parser.parse_args()
    receipt = resolve(args)
    args.receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["readiness_status"], "routing_readiness": receipt["routing_readiness"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
