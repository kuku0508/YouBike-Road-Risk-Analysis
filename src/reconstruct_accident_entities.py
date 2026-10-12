"""Phase 8.3A-2 deterministic accident-entity reconstruction."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

try:
    from .audit_accident_inputs import sha256_file
except ImportError:
    from audit_accident_inputs import sha256_file


CONTRACT_VERSION = "accident-entity-reconstruction-v1"
ENTITY_ID_PREFIX = "reconstructed_accident_"
PARTY_GROUP_COLUMNS = ["event_datetime", "location_cmp", "x_cmp", "y_cmp"]
SEVERITY_COLUMNS = ["死亡人數", "2-30日死亡人數", "受傷人數"]


class ReconstructionError(ValueError):
    """A source record cannot satisfy the reconstruction contract."""


def normalize_text(value: str) -> str:
    """Comparison-only NFC plus outer-whitespace removal; raw value is retained separately."""
    return unicodedata.normalize("NFC", str(value)).strip()


def normalize_decimal(value: str, *, digits: int | None = None) -> str:
    value = str(value).strip()
    if value == "":
        return ""
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ReconstructionError(f"invalid coordinate value: {value!r}") from exc
    if not number.is_finite():
        raise ReconstructionError(f"non-finite coordinate value: {value!r}")
    if digits is not None:
        number = number.quantize(Decimal(1).scaleb(-digits))
    text = format(number, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"-0", ""} else text


def canonical_event_key(event_datetime: str, location: str, x: str, y: str, *, digits: int | None = None) -> tuple[str, str, str, str]:
    return event_datetime, normalize_text(location), normalize_decimal(x, digits=digits), normalize_decimal(y, digits=digits)


def reconstructed_id(key: tuple[str, str, str, str]) -> str:
    payload = json.dumps(key, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return ENTITY_ID_PREFIX + hashlib.sha256(payload).hexdigest()


def strict_decode_csv(path: Path, encodings: tuple[str, ...]) -> tuple[list[str], list[list[str]], dict]:
    raw = path.read_bytes()
    decoded = None
    used = None
    for encoding in encodings:
        try:
            decoded = raw.decode(encoding)
            used = encoding
            break
        except UnicodeDecodeError:
            continue
    if decoded is None or used is None:
        raise ReconstructionError(f"cannot decode {path.name} without replacement")
    reader = csv.reader(io.StringIO(decoded), delimiter=",", strict=True)
    try:
        all_rows = list(reader)
    except csv.Error as exc:
        raise ReconstructionError(f"malformed CSV {path.name}: {exc}") from exc
    if not all_rows:
        raise ReconstructionError(f"empty CSV: {path.name}")
    header, rows = all_rows[0], all_rows[1:]
    duplicates = sorted(key for key, count in Counter(header).items() if count > 1)
    malformed = [index + 2 for index, row in enumerate(rows) if len(row) != len(header)]
    if duplicates or malformed:
        raise ReconstructionError(f"invalid CSV structure in {path.name}: duplicate headers={duplicates}, malformed rows={malformed[:5]}")
    return header, rows, {
        "encoding": "CP950" if used.lower() == "cp950" else used,
        "bom": raw.startswith(b"\xef\xbb\xbf"),
        "delimiter": ",",
        "row_count": len(rows),
        "column_count": len(header),
        "exact_duplicate_rows": len(rows) - len({tuple(row) for row in rows}),
        "empty_rows": sum(not any(value.strip() for value in row) for row in rows),
        "malformed_rows": 0,
    }


def parse_spot_datetime(value: str) -> str:
    try:
        return datetime.strptime(value.strip(), "%Y/%m/%d %H:%M").isoformat(timespec="minutes")
    except ValueError as exc:
        raise ReconstructionError(f"invalid spot-map datetime: {value!r}") from exc


def parse_party_datetime(row: pd.Series) -> str:
    try:
        value = datetime(int(row["發生年度"]) + 1911, int(row["發生月"]), int(row["發生日"]), int(row["發生時-Hours"]), int(row["發生分"]))
    except (TypeError, ValueError) as exc:
        raise ReconstructionError("invalid party datetime") from exc
    return value.isoformat(timespec="minutes")


def read_spot_map(path: Path) -> tuple[pd.DataFrame, dict]:
    header, rows, audit = strict_decode_csv(path, ("utf-8-sig", "cp950", "big5"))
    expected = ["發生時間", "處理別", "肇事地點", "座標-X", "座標-Y"]
    if header != expected:
        raise ReconstructionError(f"unsupported spot-map schema in {path.name}: {header}")
    frame = pd.DataFrame(rows, columns=header, dtype=str)
    frame["event_datetime"] = frame["發生時間"].map(parse_spot_datetime)
    frame["location_cmp"] = frame["肇事地點"].map(normalize_text)
    frame["x_cmp"] = frame["座標-X"].map(normalize_decimal)
    frame["y_cmp"] = frame["座標-Y"].map(normalize_decimal)
    audit.update({"path": path.as_posix(), "size_bytes": path.stat().st_size, "sha256": sha256_file(path), "header": header, "handling_type_distribution": {str(k): int(v) for k, v in frame["處理別"].value_counts(dropna=False).sort_index().items()}, "missing_coordinates": int(((frame["座標-X"] == "") | (frame["座標-Y"] == "")).sum())})
    return frame, audit


def read_party_detail(path: Path) -> tuple[pd.DataFrame, dict]:
    header, rows, audit = strict_decode_csv(path, ("utf-8-sig",))
    required = {"發生年度", "發生月", "發生日", "發生時-Hours", "發生分", "肇事地點", "座標-X", "座標-Y", "當事人序號", *SEVERITY_COLUMNS}
    if not required.issubset(header):
        raise ReconstructionError(f"party schema missing fields: {sorted(required - set(header))}")
    frame = pd.DataFrame(rows, columns=header, dtype=str)
    frame["event_datetime"] = frame.apply(parse_party_datetime, axis=1)
    frame["location_cmp"] = frame["肇事地點"].map(normalize_text)
    frame["x_cmp"] = frame["座標-X"].map(normalize_decimal)
    frame["y_cmp"] = frame["座標-Y"].map(normalize_decimal)
    audit.update({"path": path.as_posix(), "size_bytes": path.stat().st_size, "sha256": sha256_file(path), "header": header})
    return frame, audit


def unique_or_conflict(values: pd.Series) -> tuple[int | None, bool, bool, list[str]]:
    distinct = sorted(set(str(value) for value in values))
    if distinct == [""]:
        return None, False, True, distinct
    if len(distinct) != 1:
        return None, True, "" in distinct, distinct
    try:
        result = int(distinct[0])
    except ValueError as exc:
        raise ReconstructionError(f"non-integer severity value: {distinct[0]!r}") from exc
    if result < 0:
        raise ReconstructionError("negative severity value")
    return result, False, False, distinct


def build_party_groups(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for key, group in frame.groupby(PARTY_GROUP_COLUMNS, dropna=False, sort=False):
        severity = {}
        conflict = False
        missing = False
        evidence = {}
        for column, output in zip(SEVERITY_COLUMNS, ("death_count", "death_2_30_day_count", "injury_count")):
            value, has_conflict, has_missing, distinct = unique_or_conflict(group[column])
            severity[output] = value
            evidence[column] = distinct
            conflict |= has_conflict
            missing |= has_missing
        sequences = []
        invalid_sequence = False
        try:
            sequences = sorted(int(value) for value in group["當事人序號"] if value != "")
            invalid_sequence = sequences != list(range(1, len(group) + 1))
        except ValueError:
            invalid_sequence = True
        rows.append({
            **dict(zip(PARTY_GROUP_COLUMNS, key)),
            "party_record_count": len(group),
            **severity,
            "severity_conflict": conflict,
            "severity_missing": missing,
            "severity_evidence_json": json.dumps(evidence, ensure_ascii=False, sort_keys=True),
            "party_sequence_conflict": invalid_sequence,
            "party_raw_location_values": json.dumps(sorted(set(group["肇事地點"])), ensure_ascii=False),
        })
    return pd.DataFrame(rows)


def build_spot_groups(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for key, group in frame.groupby(PARTY_GROUP_COLUMNS, dropna=False, sort=False):
        handling = sorted(set(group["處理別"]))
        rows.append({
            **dict(zip(PARTY_GROUP_COLUMNS, key)),
            "spot_record_count": len(group),
            "handling_type": handling[0] if len(handling) == 1 else None,
            "handling_type_conflict": len(handling) != 1,
            "spot_location_raw": group.iloc[0]["肇事地點"],
            "spot_x_raw": group.iloc[0]["座標-X"],
            "spot_y_raw": group.iloc[0]["座標-Y"],
        })
    return pd.DataFrame(rows)


def classify_crosswalk(spot_groups: pd.DataFrame, party_groups: pd.DataFrame, year: int) -> pd.DataFrame:
    joined = spot_groups.merge(party_groups, on=PARTY_GROUP_COLUMNS, how="outer", indicator=True, validate="one_to_one")
    statuses = []
    ids = []
    methods = []
    for _, row in joined.iterrows():
        if row["_merge"] == "left_only":
            status = "unmatched_spot_event"
        elif row["_merge"] == "right_only":
            status = "unmatched_party_group"
        elif int(row["spot_record_count"]) != 1:
            status = "ambiguous_duplicate_spot_event"
        elif bool(row["handling_type_conflict"]):
            status = "ambiguous_handling_type"
        elif bool(row["severity_conflict"]):
            status = "severity_conflict"
        else:
            status = "exact_1to1"
        key = (row["event_datetime"], row["location_cmp"], row["x_cmp"], row["y_cmp"])
        ids.append(reconstructed_id(key) if status == "exact_1to1" else None)
        methods.append("datetime+NFC_trimmed_location+exact_decimal_XY" if status == "exact_1to1" else None)
        statuses.append(status)
    joined.insert(0, "year", year)
    joined["match_status"] = statuses
    joined["match_method"] = methods
    joined["reconstructed_accident_id"] = ids
    return joined.drop(columns=["_merge"])


def sensitivity_counts(spot: pd.DataFrame, party: pd.DataFrame) -> dict:
    result = {}
    for digits in (None, 8, 7, 6):
        spot_copy, party_copy = spot.copy(), party.copy()
        for frame in (spot_copy, party_copy):
            frame["x_cmp"] = frame["座標-X"].map(lambda value: normalize_decimal(value, digits=digits))
            frame["y_cmp"] = frame["座標-Y"].map(lambda value: normalize_decimal(value, digits=digits))
        sg, pg = build_spot_groups(spot_copy), build_party_groups(party_copy)
        joined = sg.merge(pg, on=PARTY_GROUP_COLUMNS, how="outer", indicator=True, validate="one_to_one")
        safe = (joined["_merge"] == "both") & (joined["spot_record_count"] == 1) & ~joined["severity_conflict"].fillna(False) & ~joined["party_sequence_conflict"].fillna(False)
        result["exact_decimal" if digits is None else f"round_{digits}_decimal"] = {
            "safe_1to1": int(safe.sum()),
            "spot_only_keys": int((joined["_merge"] == "left_only").sum()),
            "party_only_keys": int((joined["_merge"] == "right_only").sum()),
            "duplicate_spot_keys": int((sg["spot_record_count"] > 1).sum()),
        }
    return result


def handling_severity_audit(crosswalk: pd.DataFrame) -> dict:
    matched = crosswalk[crosswalk["match_status"] == "exact_1to1"]
    domain = {str(k): int(v) for k, v in matched["handling_type"].value_counts(dropna=False).sort_index().items()}
    type1_nonpositive_death = int(((matched["handling_type"] == "1") & (matched["death_count"] <= 0)).sum())
    type2_positive_24h_death = int(((matched["handling_type"] == "2") & (matched["death_count"] > 0)).sum())
    return {"matched_domain": domain, "type1_with_nonpositive_24h_death": type1_nonpositive_death, "type2_with_positive_24h_death": type2_positive_24h_death}


def wgs84_to_twd97(lon: float, lat: float) -> tuple[float, float]:
    """Forward TM2 sanity transform, not used for matching."""
    a = 6378137.0
    b = 6356752.314245
    lon0 = math.radians(121.0)
    k0 = 0.9999
    dx = 250000.0
    e = math.sqrt(1 - (b * b) / (a * a))
    e2 = e * e / (1 - e * e)
    n = (a - b) / (a + b)
    lat_r, lon_r = math.radians(lat), math.radians(lon)
    nu = a / math.sqrt(1 - (e * math.sin(lat_r)) ** 2)
    p = lon_r - lon0
    A = a * (1 - n + 5 * (n**2 - n**3) / 4 + 81 * (n**4 - n**5) / 64)
    B = 3 * a * n * (1 - n + 7 * (n**2 - n**3) / 8 + 55 * (n**4 - n**5) / 64) / 2
    C = 15 * a * n**2 * (1 - n + 3 * (n**2 - n**3) / 4) / 16
    D = 35 * a * n**3 * (1 - n + 11 * n**2 / 16) / 48
    E = 315 * a * n**4 * (1 - n) / 512
    S = A * lat_r - B * math.sin(2 * lat_r) + C * math.sin(4 * lat_r) - D * math.sin(6 * lat_r) + E * math.sin(8 * lat_r)
    cos_lat, tan_lat = math.cos(lat_r), math.tan(lat_r)
    x = dx + k0 * nu * cos_lat * p + k0 * nu * cos_lat**3 * (1 - tan_lat**2 + e2 * cos_lat**2) * p**3 / 6
    x += k0 * nu * cos_lat**5 * (5 - 18 * tan_lat**2 + tan_lat**4 + 14 * e2 * cos_lat**2 - 58 * e2 * cos_lat**2 * tan_lat**2) * p**5 / 120
    y = k0 * S + k0 * nu * math.sin(lat_r) * cos_lat * p**2 / 2
    y += k0 * nu * math.sin(lat_r) * cos_lat**3 * (5 - tan_lat**2 + 9 * e2 * cos_lat**2 + 4 * e2**2 * cos_lat**4) * p**4 / 24
    return x, y


def crs_sanity(spot_frames: list[pd.DataFrame], road_bbox: list[float]) -> dict:
    coordinates = []
    for frame in spot_frames:
        for x, y in frame[["座標-X", "座標-Y"]].itertuples(index=False, name=None):
            if x != "" and y != "":
                coordinates.append((float(x), float(y)))
    transformed = [wgs84_to_twd97(x, y) for x, y in coordinates]
    bbox = [min(x for x, _ in transformed), min(y for _, y in transformed), max(x for x, _ in transformed), max(y for _, y in transformed)]
    overlaps = bbox[0] <= road_bbox[2] and bbox[2] >= road_bbox[0] and bbox[1] <= road_bbox[3] and bbox[3] >= road_bbox[1]
    return {
        "assumption": "WGS84 geographic longitude/latitude treated operationally as EPSG:4326",
        "status": "accepted_reconstruction_assumption_not_source_metadata_fact",
        "transformed_point_count": len(transformed),
        "transformed_bbox_epsg3826": bbox,
        "road_bbox_epsg3826": road_bbox,
        "bbox_overlap_positive": overlaps,
        "matching_use": False,
    }


def dataframe_fingerprint(frame: pd.DataFrame, columns: list[str]) -> str:
    digest = hashlib.sha256()
    for row in frame.sort_values(columns, kind="stable")[columns].itertuples(index=False, name=None):
        digest.update((json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
    return digest.hexdigest()


def write_parquet_atomic(frame: pd.DataFrame, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), tmp, compression="zstd")
    tmp.replace(path)
    return sha256_file(path)


def reconstruct(root: Path, crosswalk_path: Path, entity_path: Path) -> dict:
    prior = json.loads((root / "notes/phase8_3a-accident-data-audit.json").read_text(encoding="utf-8"))
    if prior["audit_fingerprint_sha256"] != "0f0f75f6290c499346bf6d1b561b5be96208e37f6dd8d7c57f812c7db96f4491":
        raise ReconstructionError("Phase 8.3A audit fingerprint mismatch")
    yearly = {}
    all_crosswalk = []
    spot_frames = []
    raw_hashes = {}
    for roc_year, western_year in (("112", 2023), ("113", 2024)):
        party_path = root / f"data/raw/{roc_year}年-臺北市死傷交通事故明細.csv"
        spot_candidates = sorted((root / "data/raw").glob(f"{roc_year}年*斑點圖*.csv"))
        if len(spot_candidates) != 1:
            raise ReconstructionError(f"expected exactly one {roc_year} spot-map file, got {len(spot_candidates)}")
        spot_path = spot_candidates[0]
        spot, spot_audit = read_spot_map(spot_path)
        party, party_audit = read_party_detail(party_path)
        spot_audit["path"] = spot_path.relative_to(root).as_posix()
        party_audit["path"] = party_path.relative_to(root).as_posix()
        raw_hashes[roc_year] = {"spot_map_sha256": spot_audit["sha256"], "party_detail_sha256": party_audit["sha256"]}
        sg, pg = build_spot_groups(spot), build_party_groups(party)
        crosswalk = classify_crosswalk(sg, pg, western_year)
        counts = {str(k): int(v) for k, v in crosswalk["match_status"].value_counts().sort_index().items()}
        exact = counts.get("exact_1to1", 0)
        yearly[roc_year] = {
            "year": western_year,
            "spot_map_audit": spot_audit,
            "party_detail_audit": party_audit,
            "spot_candidate_key_count": len(sg),
            "party_group_count": len(pg),
            "match_status_counts_by_key": counts,
            "exact_1to1_rate_of_spot_rows": exact / len(spot),
            "exact_1to1_rate_of_spot_candidate_keys": exact / len(sg),
            "exact_1to1_rate_of_party_groups": exact / len(pg),
            "spot_rows_in_duplicate_candidate_keys": int(sg.loc[sg["spot_record_count"] > 1, "spot_record_count"].sum()),
            "severity_conflict_party_groups": int(pg["severity_conflict"].sum()),
            "party_sequence_conflict_groups": int(pg["party_sequence_conflict"].sum()),
            "sensitivity": sensitivity_counts(spot, party),
            "handling_severity_audit": handling_severity_audit(crosswalk),
        }
        all_crosswalk.append(crosswalk)
        spot_frames.append(spot)
    combined = pd.concat(all_crosswalk, ignore_index=True)
    entities = combined[combined["match_status"] == "exact_1to1"].copy()
    if entities["reconstructed_accident_id"].isna().any() or not entities["reconstructed_accident_id"].is_unique:
        raise ReconstructionError("reconstructed accident ID collision or null")
    entity_columns = ["reconstructed_accident_id", "year", "event_datetime", "spot_location_raw", "spot_x_raw", "spot_y_raw", "handling_type", "party_record_count", "death_count", "death_2_30_day_count", "injury_count", "severity_missing", "party_sequence_conflict", "match_status", "match_method"]
    entities = entities[entity_columns].sort_values("reconstructed_accident_id", kind="stable").reset_index(drop=True)
    combined = combined.sort_values(["year", "event_datetime", "location_cmp", "x_cmp", "y_cmp"], kind="stable").reset_index(drop=True)
    crosswalk_fp = dataframe_fingerprint(combined.fillna(""), ["year", "event_datetime", "location_cmp", "x_cmp", "y_cmp", "match_status"])
    entity_fp = dataframe_fingerprint(entities.fillna(""), entity_columns)
    crosswalk_sha = write_parquet_atomic(combined, crosswalk_path)
    entity_sha = write_parquet_atomic(entities, entity_path)
    road_bbox = prior["road_reference"]["shapefile"]["bounding_box"]
    crs = crs_sanity(spot_frames, road_bbox)
    total_spot_rows = sum(item["spot_map_audit"]["row_count"] for item in yearly.values())
    total_party_rows = sum(item["party_detail_audit"]["row_count"] for item in yearly.values())
    total_exact = len(entities)
    receipt = {
        "contract_version": CONTRACT_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "phase8_3a_audit_fingerprint": prior["audit_fingerprint_sha256"],
        "raw_file_hashes": raw_hashes,
        "matching_key_contract": {
            "fields": ["exact minute datetime", "NFC plus outer-trim comparison-only location", "exact numeric decimal X", "exact numeric decimal Y"],
            "coordinate_rounding_in_primary": None,
            "row_order_used": False,
            "forced_tie_break": False,
        },
        "yearly": yearly,
        "totals": {
            "spot_map_rows": total_spot_rows,
            "party_rows": total_party_rows,
            "spot_candidate_keys": sum(item["spot_candidate_key_count"] for item in yearly.values()),
            "party_groups": sum(item["party_group_count"] for item in yearly.values()),
            "exact_1to1_reconstructed_accidents": total_exact,
            "exact_1to1_rate_of_spot_rows": total_exact / total_spot_rows,
            "unmatched_spot_event_keys": int((combined["match_status"] == "unmatched_spot_event").sum()),
            "unmatched_party_groups": int((combined["match_status"] == "unmatched_party_group").sum()),
            "ambiguous_duplicate_spot_keys": int((combined["match_status"] == "ambiguous_duplicate_spot_event").sum()),
            "spot_rows_in_ambiguous_duplicate_keys": int(combined.loc[combined["match_status"] == "ambiguous_duplicate_spot_event", "spot_record_count"].sum()),
            "severity_conflict_keys": int((combined["match_status"] == "severity_conflict").sum()),
            "severity_conflict_party_groups": sum(item["severity_conflict_party_groups"] for item in yearly.values()),
            "reconstructed_entities_with_missing_severity": int(entities["severity_missing"].sum()),
            "reconstructed_entities_with_party_sequence_conflict": int(entities["party_sequence_conflict"].sum()),
        },
        "reconstructed_id_contract": {
            "algorithm": "reconstructed_accident_ + SHA-256(UTF-8 compact JSON canonical event key)",
            "source_status": "reconstruction artifact; not an official source accident ID",
            "stable": True,
            "deterministic": True,
            "row_order_independent": True,
            "collision_count": 0,
        },
        "crs": crs,
        "outputs": {
            "crosswalk_path": crosswalk_path.relative_to(root).as_posix(),
            "crosswalk_rows": len(combined),
            "crosswalk_fingerprint_sha256": crosswalk_fp,
            "crosswalk_sha256": crosswalk_sha,
            "entity_path": entity_path.relative_to(root).as_posix(),
            "entity_rows": len(entities),
            "entity_fingerprint_sha256": entity_fp,
            "entity_sha256": entity_sha,
        },
        "readiness": {
            "accident_entity": "READY_WITH_DISCLOSED_EXCLUSIONS_FOR_EXACT_1TO1_SUBSET",
            "crs": "READY_UNDER_EXPLICIT_RECONSTRUCTION_ASSUMPTION",
            "road_attribution_coverage": "LIMITED_TO_ROADS_WIDER_THAN_8_METRES; preserve outside_reference_coverage in Phase 8.3B",
            "phase8_3b": "READY_WITH_DISCLOSED_EXCLUSIONS",
            "remaining_exclusions": ["50 unmatched spot-map event keys", "111 unmatched party groups", "2 duplicate spot-map keys containing 4 source rows and involving 2 party groups"],
        },
        "prohibited_work_confirmed_not_performed": {
            "road_matching": False,
            "point_in_polygon": False,
            "nearest_road": False,
            "brouter_segment_matching": False,
            "distance_threshold_selected": False,
            "epdo_calculated": False,
            "cbi_calculated": False,
            "risk_analysis_started": False,
            "phase8_3b_started": False,
        },
    }
    stable = {key: value for key, value in receipt.items() if key not in {"generated_at_utc", "receipt_fingerprint_sha256"}}
    receipt["receipt_fingerprint_sha256"] = hashlib.sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return receipt


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--crosswalk", type=Path, default=root / "data/interim/accidents/accident_entity_crosswalk_2023_2024.parquet")
    parser.add_argument("--entities", type=Path, default=root / "data/processed/accidents/accident_entities_2023_2024.parquet")
    parser.add_argument("--receipt", type=Path, default=root / "notes/phase8_3a2-accident-entity-reconstruction.json")
    args = parser.parse_args()
    receipt = reconstruct(args.root.resolve(), args.crosswalk.resolve(), args.entities.resolve())
    args.receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"reconstructed_accidents": receipt["totals"]["exact_1to1_reconstructed_accidents"], "phase8_3b": receipt["readiness"]["phase8_3b"], "receipt_fingerprint": receipt["receipt_fingerprint_sha256"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
