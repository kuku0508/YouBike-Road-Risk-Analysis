"""Phase 8.0B legacy monthly station-coordinate recovery.

The source is parsed losslessly with UTF-8+surrogateescape.  Station identity is
never inferred from the legacy ``站點編號`` column or from fuzzy/geographic
similarity; only existing exact-name or versioned allowlist evidence is used.
"""
from __future__ import annotations

import argparse
import base64
import calendar
import csv
import hashlib
import io
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

try:
    from .resolve_historical_station_coordinates import dataframe_fingerprint, haversine_m, sha256_file
except ImportError:  # direct script execution
    from resolve_historical_station_coordinates import dataframe_fingerprint, haversine_m, sha256_file


MONTH_RE = re.compile(r"^youbike_(20\d{2})(0[1-9]|1[0-2])$")
CORE_MONTHS = [f"{y:04d}-{m:02d}" for y in (2023, 2024) for m in range(1, 13)]


def raw_bytes(value: str) -> bytes:
    return value.encode("utf-8", "surrogateescape")


def b64(value: str) -> str:
    return base64.b64encode(raw_bytes(value)).decode("ascii")


def safe_text(value: str) -> str:
    data = raw_bytes(value)
    try:
        return data.decode("utf-8", "strict")
    except UnicodeDecodeError:
        return data.decode("utf-8", "backslashreplace")


def contains_surrogate(value: str) -> bool:
    return any(0xDC80 <= ord(char) <= 0xDCFF for char in value)


def count_illegal_utf8(data: bytes) -> tuple[int, int]:
    decoded = data.decode("utf-8", "surrogateescape")
    invalid = [char for char in decoded if 0xDC80 <= ord(char) <= 0xDCFF]
    return len(invalid), len(set(ord(char) - 0xDC00 for char in invalid))


def coordinate_eras_from_month_coords(month_coords: dict[str, tuple[float, float]]) -> list[dict]:
    """Build exact-coordinate monthly eras for QA; gaps break an era.

    This helper never decides whether an era is evidentially acceptable.
    """
    eras: list[dict] = []
    for month in sorted(month_coords):
        coordinate = tuple(month_coords[month])
        year, number = map(int, month.split("-"))
        previous = f"{year - 1:04d}-12" if number == 1 else f"{year:04d}-{number - 1:02d}"
        if eras and eras[-1]["coordinate"] == coordinate and eras[-1]["last_month"] == previous:
            eras[-1]["last_month"] = month
        else:
            eras.append({"first_month": month, "last_month": month, "coordinate": coordinate})
    return eras


def parse_month(value: str) -> str | None:
    match = MONTH_RE.fullmatch(value)
    return f"{match.group(1)}-{match.group(2)}" if match else None


def parse_coordinate(value: str, *, latitude: bool) -> float | None:
    value = value.strip()
    if not value or value.upper() in {"NA", "NAN", "NULL"}:
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    lower, upper = ((20.0, 30.0) if latitude else (115.0, 125.0))
    return number if math.isfinite(number) and lower <= number <= upper else None


def parse_legacy(path: Path) -> tuple[pd.DataFrame, dict]:
    data = path.read_bytes()
    try:
        data.decode("utf-8", "strict")
        strict_utf8_valid = True
    except UnicodeDecodeError:
        strict_utf8_valid = False
    text = data.decode("utf-8", "surrogateescape")
    reader = csv.reader(io.StringIO(text, newline=""))
    header = next(reader)
    expected = ["", "month", "站點", "站點編號", "站點標籤", "經度", "緯度"]
    if header != expected:
        raise ValueError(f"unexpected legacy header: {[safe_text(x) for x in header]}")
    rows, malformed_width = [], 0
    invalid_field_count = invalid_record_count = 0
    for source_row, values in enumerate(reader, start=2):
        if len(values) != 7:
            malformed_width += 1
            continue
        _, month_raw, name, number, label, lon_raw, lat_raw = values
        fields = (name, number, label)
        bad_fields = sum(contains_surrogate(value) for value in fields)
        invalid_field_count += bad_fields
        invalid_record_count += bool(bad_fields)
        rows.append({
            "month_raw": safe_text(month_raw), "month": parse_month(month_raw),
            "station_name_raw": safe_text(name), "station_name_raw_base64": b64(name),
            "legacy_station_number_raw": safe_text(number), "legacy_station_number_raw_base64": b64(number),
            "station_label_raw": safe_text(label), "station_label_raw_base64": b64(label),
            "longitude": parse_coordinate(lon_raw, latitude=False), "latitude": parse_coordinate(lat_raw, latitude=True),
            "longitude_raw": safe_text(lon_raw), "latitude_raw": safe_text(lat_raw),
            "raw_row_number": source_row, "has_illegal_utf8": bool(bad_fields),
        })
    frame = pd.DataFrame(rows)
    illegal_bytes, illegal_patterns = count_illegal_utf8(data)
    audit = {
        "path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
        "encoding_mode": "utf-8 strict gate followed by utf-8+surrogateescape for lossless parsing",
        "strict_utf8_valid": strict_utf8_valid, "illegal_byte_count": illegal_bytes,
        "unique_illegal_byte_values": illegal_patterns, "illegal_station_field_count": invalid_field_count,
        "illegal_record_count": invalid_record_count, "data_row_count": len(frame),
        "column_count_including_r_rowname": len(header), "headers": expected,
        "malformed_width_rows": malformed_width,
        "legacy_number_equals_station_name_rows": int((frame.legacy_station_number_raw_base64 == frame.station_name_raw_base64).sum()),
        "legacy_number_looks_canonical_id_rows": int(frame.legacy_station_number_raw.str.fullmatch(r"500\d{6}", na=False).sum()),
    }
    return frame, audit


def load_core_monthly_names(monthly_dir: Path) -> tuple[dict[str, set[str]], dict[str, set[str]], pd.DataFrame]:
    name_ids: dict[str, set[str]] = defaultdict(set)
    station_months: dict[str, set[str]] = defaultdict(set)
    identity_rows = []
    for path in sorted(monthly_dir.glob("year=*/month=*/od.parquet")):
        year = int(path.parent.parent.name.split("=")[1]); month = int(path.parent.name.split("=")[1])
        if year not in (2023, 2024):
            continue
        stamp = f"{year:04d}-{month:02d}"
        frame = pd.read_parquet(path, columns=["origin_station_id", "destination_station_id", "origin_station_name",
                                                   "destination_station_name", "origin_city", "destination_city"])
        for side in ("origin", "destination"):
            part = frame[[f"{side}_station_id", f"{side}_station_name", f"{side}_city"]].drop_duplicates()
            for station_id, name, city in part.itertuples(index=False, name=None):
                station_id = str(station_id); name = str(name)
                name_ids[name].add(station_id); station_months[station_id].add(stamp)
                identity_rows.append((station_id, name, str(city), stamp))
    identity = pd.DataFrame(identity_rows, columns=["station_id", "name", "city", "month"])
    return name_ids, station_months, identity


def load_metadata_maps(historical: Path, taipei_current: Path, nt_current: Path, core_ids: set[str]):
    historical_map: dict[str, set[str]] = defaultdict(set)
    current_map: dict[str, set[str]] = defaultdict(set)
    id_city = {}
    with historical.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            sid = str(row["Station Number"])
            if sid in core_ids:
                historical_map[row["Station"]].add(sid); id_city[sid] = "Taipei"
    for row in json.loads(taipei_current.read_text(encoding="utf-8-sig")):
        sid = str(row["sno"])
        if sid in core_ids:
            current_map[str(row["sna"]).removeprefix("YouBike2.0_")].add(sid); id_city[sid] = "Taipei"
    with nt_current.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            sid = str(row["sno"])
            if sid in core_ids:
                current_map[str(row["sna"]).removeprefix("YouBike2.0_")].add(sid); id_city[sid] = "New Taipei"
    return historical_map, current_map, id_city


def load_allowlist(path: Path, core_ids: set[str]) -> dict[str, set[str]]:
    alias_map: dict[str, set[str]] = defaultdict(set)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if row["decision"] != "approved_repair" or row["canonical_station_id"] not in core_ids:
                continue
            alias_map[row["canonical_station_name"]].add(row["canonical_station_id"])
            # The raw value may contain escaped illegal bytes; it is intentionally
            # not normalized or decoded into a different name here.
    return alias_map


def build_mapping(legacy: pd.DataFrame, historical_map, trip_map, alias_map, current_map, id_city) -> pd.DataFrame:
    rows = []
    for name_b64, group in legacy.groupby("station_name_raw_base64", sort=True):
        name = group.station_name_raw.iloc[0]
        candidates_by_source = {
            "historical_exact": sorted(historical_map.get(name, set())),
            "trip_exact": sorted(trip_map.get(name, set())),
            "known_alias": sorted(alias_map.get(name, set())),
            "current_exact_support_only": sorted(current_map.get(name, set())),
        }
        deterministic = set(candidates_by_source["historical_exact"]) | set(candidates_by_source["trip_exact"]) | set(candidates_by_source["known_alias"])
        current_only = set(candidates_by_source["current_exact_support_only"])
        if len(deterministic) == 1:
            station_id = next(iter(deterministic))
            if candidates_by_source["historical_exact"]:
                status = "exact_historical_candidate"
            elif candidates_by_source["trip_exact"]:
                status = "exact_trip_candidate"
            else:
                status = "known_alias_candidate"
            identity_accepted = True
        elif len(deterministic) > 1:
            station_id, status, identity_accepted = None, "ambiguous", False
        elif len(current_only) == 1:
            station_id, status, identity_accepted = None, "current_only_candidate_not_accepted", False
        elif len(current_only) > 1:
            station_id, status, identity_accepted = None, "ambiguous", False
        else:
            station_id, status, identity_accepted = None, "unmatched", False
        months = sorted(group.month.dropna().unique())
        valid = group[group.longitude.notna() & group.latitude.notna()]
        rows.append({
            "legacy_station_name_raw": name, "legacy_station_name_raw_base64": name_b64,
            "mapping_status": status, "identity_accepted": identity_accepted,
            "canonical_station_id": station_id, "canonical_city": id_city.get(station_id) if station_id else None,
            "candidate_station_ids": json.dumps({k:v for k,v in candidates_by_source.items() if v}, ensure_ascii=False, sort_keys=True),
            "months_observed": len(months), "first_legacy_month": months[0] if months else None,
            "last_legacy_month": months[-1] if months else None,
            "months_with_valid_coordinate": int(valid.month.nunique()),
            "legacy_rows": int(len(group)), "valid_coordinate_rows": int(len(valid)),
            "has_illegal_utf8": bool(group.has_illegal_utf8.any()),
            "identity_evidence": "exact existing name/alias evidence only; no fuzzy, suffix stripping, or coordinate matching",
        })
    return pd.DataFrame(rows).sort_values(["mapping_status", "legacy_station_name_raw_base64"]).reset_index(drop=True)


def coordinate_timeline(legacy: pd.DataFrame, mapping: pd.DataFrame, station_months: dict[str, set[str]]) -> pd.DataFrame:
    joined = legacy.merge(mapping[["legacy_station_name_raw_base64", "canonical_station_id", "canonical_city", "mapping_status", "identity_accepted"]],
                          left_on="station_name_raw_base64", right_on="legacy_station_name_raw_base64", how="left", validate="many_to_one")
    accepted = joined[joined.identity_accepted].copy()
    rows = []
    for station_id, group in accepted.groupby("canonical_station_id"):
        valid = group[group.longitude.notna() & group.latitude.notna()].copy()
        coord_pairs = sorted(set(zip(valid.longitude, valid.latitude)))
        month_coords = valid.groupby("month").apply(lambda x: sorted(set(zip(x.longitude, x.latitude))), include_groups=False).to_dict()
        conflicting_months = sum(len(coords) > 1 for coords in month_coords.values())
        max_distance = 0.0
        for i, first in enumerate(coord_pairs):
            for second in coord_pairs[i+1:]:
                max_distance = max(max_distance, haversine_m(first, second))
        if len(coord_pairs) <= 1:
            stability = "stable_exact_coordinate"
        elif max_distance < 5:
            stability = "precision_level_variation_candidate"
        else:
            stability = "coordinate_change_candidate"
        legacy_valid_months = set(valid.month.dropna())
        relevant_months = station_months.get(str(station_id), set())
        missing_relevant = sorted(relevant_months - legacy_valid_months)
        rows.append({
            "station_id": str(station_id), "city": group.canonical_city.dropna().iloc[0] if group.canonical_city.notna().any() else None,
            "legacy_names": json.dumps(sorted(group.station_name_raw.unique()), ensure_ascii=False),
            "first_legacy_month": group.month.dropna().min(), "last_legacy_month": group.month.dropna().max(),
            "months_observed": int(group.month.nunique()), "months_with_valid_coordinate": int(valid.month.nunique()),
            "routing_relevant_months": len(relevant_months), "routing_months_missing_coordinate": len(missing_relevant),
            "missing_routing_months": json.dumps(missing_relevant), "distinct_coordinate_pairs": len(coord_pairs),
            "coordinate_pairs": json.dumps(coord_pairs), "max_displacement_m": max_distance,
            "months_with_competing_coordinates": conflicting_months, "stability_status": stability,
            "temporally_complete_support": bool(relevant_months and not missing_relevant and len(coord_pairs) == 1),
            "provenance_acceptance": "supporting_only_unverified_provenance",
            "routing_accepted_from_legacy": False,
        })
    return pd.DataFrame(rows).sort_values("station_id").reset_index(drop=True), joined


def station_impacts(od: pd.DataFrame, station_status: pd.DataFrame, status_column: str) -> pd.DataFrame:
    nonself = od[od.origin_station_id != od.destination_station_id]
    endpoint = pd.concat([
        nonself[["origin_station_id", "destination_station_id", "trip_count"]].rename(columns={"origin_station_id":"station_id", "destination_station_id":"counterpart"}),
        nonself[["destination_station_id", "origin_station_id", "trip_count"]].rename(columns={"destination_station_id":"station_id", "origin_station_id":"counterpart"}),
    ], ignore_index=True)
    impact = endpoint.groupby("station_id", as_index=False).agg(affected_non_self_od_edges=("trip_count","size"),
                                                                 affected_non_self_trip_weight=("trip_count","sum"),
                                                                 counterpart_station_count=("counterpart","nunique"))
    return station_status.merge(impact, on="station_id", how="left").fillna({"affected_non_self_od_edges":0,"affected_non_self_trip_weight":0,"counterpart_station_count":0})


def union_impact(od: pd.DataFrame, station_ids: set[str]) -> dict:
    nonself = od[od.origin_station_id != od.destination_station_id]
    involved = nonself.origin_station_id.isin(station_ids) | nonself.destination_station_id.isin(station_ids)
    both = nonself.origin_station_id.isin(station_ids) & nonself.destination_station_id.isin(station_ids)
    return {
        "stations": len(station_ids),
        "endpoint_involved_non_self_od_edges": int(involved.sum()),
        "endpoint_involved_non_self_trip_weight": int(nonself.loc[involved, "trip_count"].sum()),
        "both_endpoints_in_status_non_self_od_edges": int(both.sum()),
        "both_endpoints_in_status_non_self_trip_weight": int(nonself.loc[both, "trip_count"].sum()),
    }


def load_official_coordinates(historical: Path, taipei_current: Path) -> tuple[dict, dict]:
    old, new = {}, {}
    with historical.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            old[str(row["Station Number"])] = (float(row["Longitude"]), float(row["Latitude"]))
    for row in json.loads(taipei_current.read_text(encoding="utf-8-sig")):
        new[str(row["sno"])] = (float(row["longitude"]), float(row["latitude"]))
    return old, new


def build_legacy_evidence(joined: pd.DataFrame, source_hash: str) -> pd.DataFrame:
    mapped = joined[joined.identity_accepted & joined.longitude.notna() & joined.latitude.notna()].copy()
    return pd.DataFrame({
        "station_id": mapped.canonical_station_id.astype(str), "station_name": mapped.station_name_raw,
        "city": mapped.canonical_city, "latitude": mapped.latitude, "longitude": mapped.longitude,
        "source_name": "active_station_all.csv", "source_url_or_reference": "user-provided legacy project file",
        "source_date": mapped.month, "snapshot_date": mapped.month, "valid_from": None, "valid_to": None,
        "source_type": "legacy_monthly_station_csv", "official_status": "provenance_unverified_supporting_only",
        "retrieval_date": "2026-09-19", "source_hash": source_hash,
        "evidence_notes": "Month semantics and official upstream provenance unresolved; exact deterministic identity mapping only.",
        "original_legacy_name": mapped.station_name_raw, "original_legacy_name_base64": mapped.station_name_raw_base64,
        "legacy_station_number_raw": mapped.legacy_station_number_raw,
        "legacy_station_number_raw_base64": mapped.legacy_station_number_raw_base64,
        "legacy_month": mapped.month, "identity_evidence": mapped.mapping_status,
        "provenance_status": "unverified", "acceptance_tier": "supporting_not_routing_accepted",
        "raw_row_number": mapped.raw_row_number,
    })


def main(args) -> dict:
    root = args.root.resolve()
    legacy, raw_audit = parse_legacy(args.source)
    core = legacy[legacy.month.isin(CORE_MONTHS)].copy()
    invalid_month_rows = int(legacy.month.isna().sum())
    both = core.longitude.notna() & core.latitude.notna()
    partial = core.longitude.isna() ^ core.latitude.isna()
    name_coord = core[both][["station_name_raw_base64", "longitude", "latitude"]].drop_duplicates()

    od = pd.read_parquet(args.od)
    core_ids = set(od.origin_station_id.astype(str)) | set(od.destination_station_id.astype(str))
    trip_map, station_months, trip_identity = load_core_monthly_names(args.monthly_od)
    hist_map, current_map, id_city = load_metadata_maps(args.historical, args.taipei_current, args.nt_current, core_ids)
    alias_map = load_allowlist(args.allowlist, core_ids)
    mapping = build_mapping(core, hist_map, trip_map, alias_map, current_map, id_city)
    timeline, joined = coordinate_timeline(core, mapping, station_months)
    legacy_evidence = build_legacy_evidence(joined, raw_audit["sha256"])

    old_ledger = pd.read_parquet(args.phase8a_ledger)
    # Idempotent integration: a rerun may read the prior combined ledger from
    # the same path. Preserve every non-legacy Phase 8.0A row, but replace this
    # source's append set rather than recursively appending it.
    if "source_type" in old_ledger:
        old_ledger = old_ledger[old_ledger.source_type != "legacy_monthly_station_csv"].copy()
    for column in legacy_evidence.columns:
        if column not in old_ledger:
            old_ledger[column] = None
    for column in old_ledger.columns:
        if column not in legacy_evidence:
            legacy_evidence[column] = None
    combined_ledger = pd.concat([old_ledger, legacy_evidence[old_ledger.columns]], ignore_index=True)
    combined_ledger = combined_ledger.sort_values(["station_id", "snapshot_date", "source_name", "raw_row_number"], na_position="first").reset_index(drop=True)

    args.interim.mkdir(parents=True, exist_ok=True)
    mapping_path = args.interim / "legacy_station_name_mapping.parquet"
    evidence_path = args.interim / "legacy_coordinate_evidence.parquet"
    anomaly_path = args.interim / "legacy_station_name_anomalies.parquet"
    timeline_path = args.interim / "legacy_coordinate_timeline.parquet"
    combined_path = args.interim / "station_coordinate_evidence.parquet"
    mapping.to_parquet(mapping_path, index=False)
    legacy_evidence.to_parquet(evidence_path, index=False)
    mapping[~mapping.identity_accepted].to_parquet(anomaly_path, index=False)
    timeline.to_parquet(timeline_path, index=False)
    combined_ledger.to_parquet(combined_path, index=False)

    prior = json.loads(args.phase8a_receipt.read_text(encoding="utf-8"))
    conflict_ids = set(pd.read_parquet(args.phase8a_conflicts).station_id.astype(str))
    current_only = pd.read_parquet(args.phase8a_unresolved)
    current_only = current_only[current_only.reason_unresolved == "current_only_without_temporal_support"]
    mapped_ids = set(timeline.station_id)
    conflicts_timeline = timeline[timeline.station_id.isin(conflict_ids)].copy()
    current_recovery = current_only.assign(
        legacy_identity_mapped=current_only.station_id.isin(mapped_ids),
        legacy_temporally_complete=current_only.station_id.isin(set(timeline.loc[timeline.temporally_complete_support, "station_id"])),
    )

    status_counts = Counter(mapping.mapping_status)
    mapped_city = Counter(timeline.city)
    current_city = current_recovery.groupby("city").agg(nodes=("station_id","size"), identity_mapped=("legacy_identity_mapped","sum"),
                                                          temporally_complete_support=("legacy_temporally_complete","sum")).to_dict("index")
    stability = Counter(timeline.stability_status)
    official_old, official_new = load_official_coordinates(args.historical, args.taipei_current)
    conflict_rows = []
    for row in conflicts_timeline.itertuples(index=False):
        pairs = [tuple(value) for value in json.loads(row.coordinate_pairs)]
        old = official_old.get(row.station_id); new = official_new.get(row.station_id)
        matches_old = bool(old and pairs and all(haversine_m(pair, old) < 0.01 for pair in pairs))
        matches_new = bool(new and pairs and all(haversine_m(pair, new) < 0.01 for pair in pairs))
        if matches_old and row.temporally_complete_support:
            finding = "legacy_supports_2024_coordinate_through_routing_months"
        elif matches_old:
            finding = "legacy_supports_2024_coordinate_with_month_gaps"
        elif matches_new:
            finding = "legacy_matches_2026_coordinate"
        else:
            finding = "legacy_competes_with_both_official_snapshots"
        conflict_rows.append({
            "station_id": row.station_id, "city": row.city, "legacy_first_month": row.first_legacy_month,
            "legacy_last_month": row.last_legacy_month, "legacy_coordinate_pairs": row.coordinate_pairs,
            "official_2024_coordinate": json.dumps(old), "official_2026_coordinate": json.dumps(new),
            "legacy_matches_2024": matches_old, "legacy_matches_2026": matches_new,
            "temporally_complete_support": bool(row.temporally_complete_support),
            "supporting_finding": finding, "routing_resolution": "unresolved_provenance_gate",
        })
    conflict_detail = pd.DataFrame(conflict_rows).sort_values("station_id")
    conflict_detail_path = args.interim / "legacy_phase8a_conflict_timeline.parquet"
    conflict_detail.to_parquet(conflict_detail_path, index=False)

    status_station_ids = {}
    for status, frame in mapping[mapping.identity_accepted].groupby("mapping_status"):
        status_station_ids[status] = set(frame.canonical_station_id.dropna().astype(str))
    mapping_quality = {status: union_impact(od, ids) for status, ids in status_station_ids.items()}
    mapping_quality["ambiguous"] = {**union_impact(od, set()), "legacy_names": int((mapping.mapping_status == "ambiguous").sum())}
    mapping_quality["unmatched"] = {**union_impact(od, set()), "legacy_names": int((mapping.mapping_status == "unmatched").sum())}
    mapping_station_status = timeline[["station_id", "city", "temporally_complete_support"]].copy()
    mapping_station_status["mapping_quality"] = "exact_identity_supporting_only"
    impacts = station_impacts(od, mapping_station_status, "mapping_quality")
    impact_summary = {
        "mapped_station_individual_edge_involvement": int(impacts.affected_non_self_od_edges.sum()),
        "mapped_station_individual_trip_involvement": int(impacts.affected_non_self_trip_weight.sum()),
        "note": "Individual station impacts overlap and are not union coverage.",
    }
    receipt = {
        "phase": "8.0B", "full_routing_executed": False,
        "source": {**raw_audit, "retrieval_status": "user-provided local raw file; raw bytes unchanged"},
        "provenance": {
            "result": "unverified", "repository_reference_found": False, "git_history_reference_found": False,
            "upstream_official_source_found": False,
            "month_semantics": "unknown monthly observation/group label; not promoted to month-end snapshot",
            "evidence_acceptance": "supporting_only; cannot independently make a station routing-ready",
        },
        "profile": {
            "invalid_month_rows": invalid_month_rows, "available_months": sorted(legacy.month.dropna().unique()),
            "core_months": sorted(core.month.unique()), "core_month_count": int(core.month.nunique()),
            "core_rows": int(len(core)), "core_rows_both_coordinates": int(both.sum()),
            "core_rows_missing_any_coordinate": int((~both).sum()), "core_rows_one_coordinate_only": int(partial.sum()),
            "distinct_legacy_names_core": int(core.station_name_raw_base64.nunique()),
            "distinct_name_coordinate_histories": int(len(name_coord)),
        },
        "mapping": {
            "legacy_name_count": int(len(mapping)), "status_counts": dict(status_counts),
            "identity_mapped_unique_station_ids": int(timeline.station_id.nunique()),
            "mapped_city_counts": dict(mapped_city),
            "canonical_ids_receiving_multiple_legacy_names": int((timeline.legacy_names.str.count('", "') + 1 > 1).sum()),
            "collision_name_count": int((mapping.mapping_status == "ambiguous").sum()),
            "legacy_number_is_not_canonical_id": raw_audit["legacy_number_looks_canonical_id_rows"] == 0,
            "quality_by_status": mapping_quality,
        },
        "coordinates": {
            "stability_status_counts": dict(stability),
            "temporally_complete_supporting_station_count": int(timeline.temporally_complete_support.sum()),
            "coordinate_conflict_candidate_count": int((timeline.stability_status != "stable_exact_coordinate").sum()),
            "confirmed_within_period_relocations": 0,
            "coordinate_era_count": 0,
            "reason_no_confirmed_relocation": "source provenance is unverified; coordinate changes remain candidates",
        },
        "phase8a_conflicts": {
            "total": len(conflict_ids), "identity_mapped_in_legacy": int(len(set(conflicts_timeline.station_id))),
            "temporally_complete_support": int(conflicts_timeline.temporally_complete_support.sum()) if len(conflicts_timeline) else 0,
            "legacy_matches_2024_coordinate": int(conflict_detail.legacy_matches_2024.sum()),
            "legacy_matches_2026_coordinate": int(conflict_detail.legacy_matches_2026.sum()),
            "resolved_for_routing": 0,
        },
        "phase8a_current_only": {
            "total": int(len(current_only)), "identity_mapped_in_legacy": int(current_recovery.legacy_identity_mapped.sum()),
            "temporally_complete_support": int(current_recovery.legacy_temporally_complete.sum()),
            "resolved_for_routing": 0, "by_city": current_city,
        },
        "mapping_impact": impact_summary,
        "routing_readiness_before": prior["routing_readiness"],
        "routing_readiness_after": prior["routing_readiness"],
        "routing_contract_version": prior["routing_contract_version"],
        "artifacts": {
            "mapping": {"path": mapping_path.relative_to(root).as_posix(), "rows": len(mapping), "sha256": sha256_file(mapping_path)},
            "legacy_evidence": {"path": evidence_path.relative_to(root).as_posix(), "rows": len(legacy_evidence), "sha256": sha256_file(evidence_path)},
            "anomalies": {"path": anomaly_path.relative_to(root).as_posix(), "rows": int((~mapping.identity_accepted).sum()), "sha256": sha256_file(anomaly_path)},
            "timeline": {"path": timeline_path.relative_to(root).as_posix(), "rows": len(timeline), "sha256": sha256_file(timeline_path)},
            "phase8a_conflict_timeline": {"path": conflict_detail_path.relative_to(root).as_posix(), "rows": len(conflict_detail), "sha256": sha256_file(conflict_detail_path)},
            "combined_evidence_ledger": {"path": combined_path.relative_to(root).as_posix(), "rows": len(combined_ledger), "sha256": sha256_file(combined_path)},
            "final_coordinate_artifact_unchanged": prior["artifacts"]["final_coordinate_artifact"],
        },
        "deterministic_fingerprints": {
            "mapping": dataframe_fingerprint(mapping, ["legacy_station_name_raw_base64", "mapping_status", "canonical_station_id"]),
            "timeline": dataframe_fingerprint(timeline, ["station_id", "coordinate_pairs", "stability_status", "temporally_complete_support"]),
        },
        "readiness_status": "LEGACY HISTORICAL COORDINATES: NOT SUFFICIENTLY TRACEABLE",
    }
    args.receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return receipt


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--source", type=Path, default=root/"data/raw/active_station_all.csv")
    parser.add_argument("--od", type=Path, default=root/"data/processed/od/aggregate/core_2023_2024/od.parquet")
    parser.add_argument("--monthly-od", type=Path, default=root/"data/processed/od/monthly")
    parser.add_argument("--historical", type=Path, default=root/"data/raw/station_snapshot_2024-05-31.csv")
    parser.add_argument("--taipei-current", type=Path, default=root/"data/raw/youbike_immediate_2026-09-13.json")
    parser.add_argument("--nt-current", type=Path, default=root/"data/raw/new_taipei_youbike_2026-09-14.csv")
    parser.add_argument("--allowlist", type=Path, default=root/"config/station_repair_allowlist.csv")
    parser.add_argument("--phase8a-ledger", type=Path, default=root/"data/interim/routing/station_coordinate_evidence.parquet")
    parser.add_argument("--phase8a-conflicts", type=Path, default=root/"data/interim/routing/routing_coordinate_conflicts.parquet")
    parser.add_argument("--phase8a-unresolved", type=Path, default=root/"data/processed/routing/routing_coordinate_unresolved.parquet")
    parser.add_argument("--phase8a-receipt", type=Path, default=root/"notes/historical-coordinate-resolution-receipt.json")
    parser.add_argument("--interim", type=Path, default=root/"data/interim/routing")
    parser.add_argument("--receipt", type=Path, default=root/"notes/legacy-coordinate-recovery-receipt.json")
    parsed = parser.parse_args()
    result = main(parsed)
    print(json.dumps({"status": result["readiness_status"], "profile": result["profile"], "mapping": result["mapping"]}, ensure_ascii=False))
