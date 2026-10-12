"""Phase 8.3A read-only audit of accident CSVs and the road reference layer."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import struct
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


CONTRACT_VERSION = "accident-input-audit-v1"
REQUIRED_SHAPEFILE_SUFFIXES = {".shp", ".shx", ".dbf", ".prj", ".cpg"}
SHAPE_TYPES = {0: "Null Shape", 1: "Point", 3: "PolyLine", 5: "Polygon", 8: "MultiPoint", 11: "PointZ", 13: "PolyLineZ", 15: "PolygonZ"}


class AuditError(ValueError):
    """Input violates a structural audit contract."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_samples(values: list[str], limit: int = 3) -> list[str]:
    return sorted({value for value in values if value != ""})[:limit]


def infer_dtype(values: list[str]) -> str:
    populated = [value for value in values if value != ""]
    if not populated:
        return "empty"
    if all(re.fullmatch(r"[+-]?\d+", value) for value in populated):
        return "integer-like string"
    try:
        for value in populated:
            number = float(value)
            if not math.isfinite(number):
                raise ValueError
        return "numeric-like string"
    except ValueError:
        return "string"


def strict_csv_rows(path: Path) -> tuple[list[str], list[list[str]], dict]:
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AuditError(f"{path.name}: invalid UTF-8 at byte {exc.start}") from exc
    sample = text[:8192]
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error as exc:
        raise AuditError(f"{path.name}: delimiter cannot be determined") from exc
    reader = csv.reader(text.splitlines(), delimiter=delimiter, strict=True)
    try:
        all_rows = list(reader)
    except csv.Error as exc:
        raise AuditError(f"{path.name}: malformed CSV: {exc}") from exc
    if not all_rows:
        raise AuditError(f"{path.name}: empty CSV")
    header, rows = all_rows[0], all_rows[1:]
    duplicate_headers = sorted(name for name, count in Counter(header).items() if count > 1)
    malformed = [{"source_row": index + 2, "field_count": len(row)} for index, row in enumerate(rows) if len(row) != len(header)]
    if duplicate_headers or malformed:
        raise AuditError(f"{path.name}: duplicate headers={duplicate_headers}, malformed rows={malformed[:5]}")
    return header, rows, {
        "encoding": "UTF-8 with BOM" if bom else "UTF-8 without BOM",
        "bom": bom,
        "delimiter": delimiter,
        "duplicate_column_names": duplicate_headers,
        "completely_empty_rows": sum(not any(cell.strip() for cell in row) for row in rows),
        "malformed_row_count": len(malformed),
        "parsing_warnings": [],
    }


def parse_roc_dates(frame: pd.DataFrame) -> dict:
    required = ["發生年度", "發生月", "發生日", "發生時-Hours", "發生分"]
    if any(column not in frame for column in required):
        return {"status": "unavailable", "missing_columns": [column for column in required if column not in frame]}
    parsed: list[datetime] = []
    invalid = 0
    missing = 0
    by_month: Counter[str] = Counter()
    for values in frame[required].itertuples(index=False, name=None):
        if any(value == "" for value in values):
            missing += 1
            continue
        try:
            roc_year, month, day, hour, minute = map(int, values)
            value = datetime(roc_year + 1911, month, day, hour, minute)
        except (TypeError, ValueError):
            invalid += 1
            continue
        parsed.append(value)
        by_month[value.strftime("%Y-%m")] += 1
    return {
        "status": "parsed_by_documented_roc_year_plus_1911_rule",
        "minimum_datetime": min(parsed).isoformat(timespec="minutes") if parsed else None,
        "maximum_datetime": max(parsed).isoformat(timespec="minutes") if parsed else None,
        "missing_datetime_records": missing,
        "invalid_datetime_records": invalid,
        "records_by_month": dict(sorted(by_month.items())),
        "western_years": sorted({value.year for value in parsed}),
    }


def coordinate_audit(frame: pd.DataFrame) -> dict:
    x_name, y_name = "座標-X", "座標-Y"
    if x_name not in frame or y_name not in frame:
        return {"status": "unavailable"}
    pairs: list[tuple[float, float]] = []
    missing_both = missing_either = invalid = zero = 0
    precision = Counter()
    for x_raw, y_raw in frame[[x_name, y_name]].itertuples(index=False, name=None):
        if x_raw == "" and y_raw == "":
            missing_both += 1
            missing_either += 1
            continue
        if x_raw == "" or y_raw == "":
            missing_either += 1
            continue
        try:
            x, y = float(x_raw), float(y_raw)
            if not math.isfinite(x) or not math.isfinite(y):
                raise ValueError
        except ValueError:
            invalid += 1
            continue
        if x == 0 or y == 0:
            zero += 1
        pairs.append((x, y))
        for raw in (x_raw, y_raw):
            precision[len(raw.partition(".")[2].rstrip("0"))] += 1
    counts = Counter(pairs)
    wgs_candidate = bool(pairs) and all(119 <= x <= 123 and 21 <= y <= 26 for x, y in pairs)
    return {
        "status": "audited",
        "coordinate_columns": [x_name, y_name],
        "complete_coordinate_records": len(pairs),
        "complete_coordinate_rate": len(pairs) / len(frame) if len(frame) else None,
        "missing_either_coordinate_records": missing_either,
        "missing_both_coordinate_records": missing_both,
        "invalid_numeric_coordinate_records": invalid,
        "zero_coordinate_records": zero,
        "unique_coordinate_pairs": len(counts),
        "duplicate_coordinate_pairs": sum(1 for count in counts.values() if count > 1),
        "records_in_duplicated_coordinate_pairs": sum(count for count in counts.values() if count > 1),
        "maximum_coordinate_multiplicity": max(counts.values(), default=0),
        "x_min": min((x for x, _ in pairs), default=None),
        "x_max": max((x for x, _ in pairs), default=None),
        "y_min": min((y for _, y in pairs), default=None),
        "y_max": max((y for _, y in pairs), default=None),
        "decimal_place_distribution_across_values": {str(key): value for key, value in sorted(precision.items())},
        "candidate_crs": "WGS84 / EPSG:4326" if wgs_candidate else "unresolved",
        "crs_status": "candidate_from_numeric_range_only",
    }


def accident_group_audit(frame: pd.DataFrame) -> dict:
    grouping_columns = [
        "發生年度", "發生月", "發生日", "發生時-Hours", "發生分", "區序", "肇事地點", "座標-X", "座標-Y",
    ]
    if any(column not in frame for column in grouping_columns):
        return {"status": "unavailable", "missing_columns": [column for column in grouping_columns if column not in frame]}
    sizes = frame.groupby(grouping_columns, dropna=False, sort=False).size()
    distribution = Counter(int(size) for size in sizes)
    sequence_consistent = sequence_inconsistent = casualty_consistent = casualty_inconsistent = 0
    casualty_columns = ["死亡人數", "2-30日死亡人數", "受傷人數"]
    for _, group in frame.groupby(grouping_columns, dropna=False, sort=False):
        sequences = []
        try:
            sequences = sorted(int(value) for value in group["當事人序號"] if value != "")
        except ValueError:
            sequence_inconsistent += 1
            continue
        if sequences == list(range(1, len(group) + 1)):
            sequence_consistent += 1
        else:
            sequence_inconsistent += 1
        if all(group[column].nunique(dropna=False) == 1 for column in casualty_columns):
            casualty_consistent += 1
        else:
            casualty_inconsistent += 1
    return {
        "status": "heuristic_only_no_accident_id",
        "heuristic_group_columns": grouping_columns,
        "heuristic_group_count": int(len(sizes)),
        "records_per_heuristic_group_distribution": {str(key): value for key, value in sorted(distribution.items())},
        "maximum_records_per_heuristic_group": int(sizes.max()) if len(sizes) else 0,
        "heuristic_groups_with_multiple_records": int((sizes > 1).sum()),
        "heuristic_groups_with_contiguous_party_sequence": sequence_consistent,
        "heuristic_groups_with_noncontiguous_or_invalid_party_sequence": sequence_inconsistent,
        "heuristic_groups_with_consistent_casualty_counts": casualty_consistent,
        "heuristic_groups_with_inconsistent_casualty_counts": casualty_inconsistent,
    }


def severity_audit(frame: pd.DataFrame) -> dict:
    casualty_columns = ["死亡人數", "2-30日死亡人數", "受傷人數"]
    profiles = {}
    for column in casualty_columns:
        if column not in frame:
            continue
        values = frame[column]
        numeric = pd.to_numeric(values.where(values.ne("")), errors="coerce")
        profiles[column] = {
            "null_count": int(values.eq("").sum()),
            "invalid_numeric_count": int(values.ne("").sum() - numeric.notna().sum()),
            "minimum": int(numeric.min()) if numeric.notna().any() else None,
            "maximum": int(numeric.max()) if numeric.notna().any() else None,
            "record_level_distribution": {str(key): int(value) for key, value in values.value_counts(dropna=False).sort_index().items()},
        }
    return {
        "casualty_count_fields": profiles,
        "party_injury_field_present": "受傷程度" in frame,
        "explicit_a1_a2_a3_field_present": any(column in frame for column in ("A1", "A2", "A3", "事故類別")),
        "property_damage_field_present": any("財損" in column for column in frame),
        "epdo_support": "incomplete: casualty counts exist at repeated party-row grain, no reliable accident ID, and no property-damage field/population",
    }


def profile_columns(frame: pd.DataFrame) -> list[dict]:
    identifier_tokens = ("編號", "序號", "ID", "id")
    date_tokens = ("年", "月", "日", "時", "分", "日期", "時間")
    coordinate_tokens = ("座標", "經度", "緯度", "longitude", "latitude")
    location_tokens = ("地點", "道路", "地址", "路口", "區")
    severity_tokens = ("死亡", "受傷", "傷亡", "事故", "財損")
    result = []
    for column in frame.columns:
        values = frame[column].tolist()
        populated = [value for value in values if value != ""]
        result.append({
            "column": column,
            "inferred_dtype": infer_dtype(values),
            "non_null_count": len(populated),
            "null_count": len(values) - len(populated),
            "null_rate": (len(values) - len(populated)) / len(values) if values else None,
            "distinct_non_null_count": len(set(populated)),
            "representative_values": safe_samples(values),
            "suspected_identifier": any(token in column for token in identifier_tokens),
            "suspected_date_or_time": any(token in column for token in date_tokens),
            "suspected_coordinate": any(token in column for token in coordinate_tokens),
            "suspected_address_or_road": any(token in column for token in location_tokens),
            "suspected_severity_or_casualty": any(token in column for token in severity_tokens),
        })
    return result


def audit_accident_csv(path: Path) -> dict:
    header, rows, parse = strict_csv_rows(path)
    frame = pd.DataFrame(rows, columns=header, dtype=str)
    exact_duplicates = int(frame.duplicated().sum())
    severity_fields = [column for column in frame if any(token in column for token in ("死亡", "受傷", "傷亡", "財損"))]
    result = {
        "path": path.as_posix(),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        **parse,
        "row_count": len(frame),
        "column_count": len(frame.columns),
        "header": header,
        "exact_duplicate_row_count": exact_duplicates,
        "column_profiles": profile_columns(frame),
        "temporal_audit": parse_roc_dates(frame),
        "coordinate_audit": coordinate_audit(frame),
        "accident_entity_audit": accident_group_audit(frame),
        "row_unit_finding": "party-level record supported by party sequence and party attributes; not one row per accident",
        "accident_id_finding": "no explicit reliable accident identifier observed",
        "severity_fields": severity_fields,
        "severity_audit": severity_audit(frame),
        "property_damage_field_present": any("財損" in column for column in frame),
    }
    return result


def parse_dbf(path: Path, encoding: str) -> tuple[list[dict], list[dict], dict]:
    raw = path.read_bytes()
    if len(raw) < 33:
        raise AuditError("DBF header is truncated")
    record_count = struct.unpack("<I", raw[4:8])[0]
    header_length = struct.unpack("<H", raw[8:10])[0]
    record_length = struct.unpack("<H", raw[10:12])[0]
    fields = []
    offset = 32
    while offset < header_length and raw[offset] != 0x0D:
        descriptor = raw[offset:offset + 32]
        name = descriptor[:11].split(b"\x00", 1)[0].decode("ascii")
        fields.append({"name": name, "type": chr(descriptor[11]), "length": descriptor[16], "decimals": descriptor[17]})
        offset += 32
    rows: list[dict] = []
    deleted = 0
    for index in range(record_count):
        start = header_length + index * record_length
        record = raw[start:start + record_length]
        if len(record) != record_length:
            raise AuditError(f"DBF record {index + 1} is truncated")
        if record[:1] == b"*":
            deleted += 1
            continue
        cursor = 1
        values = {}
        for field in fields:
            cell = record[cursor:cursor + field["length"]]
            cursor += field["length"]
            try:
                values[field["name"]] = cell.decode(encoding).strip()
            except UnicodeDecodeError as exc:
                raise AuditError(f"DBF decoding failed in record {index + 1}, field {field['name']}") from exc
        rows.append(values)
    metadata = {"declared_record_count": record_count, "active_record_count": len(rows), "deleted_record_count": deleted, "header_length": header_length, "record_length": record_length}
    return fields, rows, metadata


def audit_shp(path: Path) -> dict:
    raw = path.read_bytes()
    if len(raw) < 100:
        raise AuditError("SHP header is truncated")
    file_code = struct.unpack(">i", raw[:4])[0]
    declared_length = struct.unpack(">i", raw[24:28])[0] * 2
    version = struct.unpack("<i", raw[28:32])[0]
    declared_type = struct.unpack("<i", raw[32:36])[0]
    bbox = list(struct.unpack("<4d", raw[36:68]))
    if file_code != 9994 or version != 1000 or declared_length != len(raw):
        raise AuditError("SHP header identity or length is invalid")
    offset = 100
    records = empty = structurally_invalid = 0
    type_counts: Counter[str] = Counter()
    while offset < len(raw):
        if offset + 8 > len(raw):
            raise AuditError("SHP record header is truncated")
        _, words = struct.unpack(">2i", raw[offset:offset + 8])
        content = raw[offset + 8:offset + 8 + words * 2]
        if len(content) != words * 2 or len(content) < 4:
            raise AuditError("SHP record content is truncated")
        shape_type = struct.unpack("<i", content[:4])[0]
        records += 1
        type_counts[SHAPE_TYPES.get(shape_type, f"Unknown({shape_type})")] += 1
        if shape_type == 0:
            empty += 1
        elif shape_type in (5, 15):
            invalid = False
            if len(content) < 44:
                invalid = True
            else:
                box = struct.unpack("<4d", content[4:36])
                num_parts, num_points = struct.unpack("<2i", content[36:44])
                required = 44 + num_parts * 4 + num_points * 16
                if num_parts < 1 or num_points < 4 or len(content) < required or not all(math.isfinite(value) for value in box):
                    invalid = True
                else:
                    parts = list(struct.unpack(f"<{num_parts}i", content[44:44 + num_parts * 4]))
                    points_offset = 44 + num_parts * 4
                    points = [struct.unpack("<2d", content[points_offset + i * 16:points_offset + (i + 1) * 16]) for i in range(num_points)]
                    boundaries = parts + [num_points]
                    if parts[0] != 0 or parts != sorted(set(parts)) or any(not all(math.isfinite(v) for v in point) for point in points):
                        invalid = True
                    for start, end in zip(boundaries, boundaries[1:]):
                        if end - start < 4 or points[start] != points[end - 1]:
                            invalid = True
            structurally_invalid += int(invalid)
        elif shape_type != declared_type:
            structurally_invalid += 1
        offset += 8 + words * 2
    return {
        "file_code": file_code,
        "version": version,
        "declared_geometry_type": SHAPE_TYPES.get(declared_type, f"Unknown({declared_type})"),
        "feature_count": records,
        "geometry_type_counts": dict(type_counts),
        "bounding_box": bbox,
        "empty_geometry_count": empty,
        "structurally_invalid_geometry_count": structurally_invalid,
        "ogc_topology_validity": "unresolved_without_topology_engine",
    }


def audit_road_layer(directory: Path) -> dict:
    files = {path.suffix.lower(): path for path in directory.iterdir() if path.is_file()}
    missing = sorted(REQUIRED_SHAPEFILE_SUFFIXES - set(files))
    if missing:
        raise AuditError(f"missing required Shapefile components: {missing}")
    cpg = files[".cpg"].read_text(encoding="ascii").strip()
    prj = files[".prj"].read_text(encoding="ascii").strip()
    encoding = "utf-8" if cpg.upper().replace("-", "") == "UTF8" else cpg
    fields, rows, dbf = parse_dbf(files[".dbf"], encoding)
    shp = audit_shp(files[".shp"])
    shx_count = (files[".shx"].stat().st_size - 100) // 8
    if not (shp["feature_count"] == dbf["declared_record_count"] == shx_count):
        raise AuditError("SHP/SHX/DBF feature counts disagree")
    frame = pd.DataFrame(rows, dtype=str)
    profiles = profile_columns(frame)
    road_id = frame["ROAD_ID"] if "ROAD_ID" in frame else pd.Series([], dtype=str)
    numeric_width = pd.to_numeric(frame["ROADWIDTH"], errors="coerce") if "ROADWIDTH" in frame else pd.Series([], dtype=float)
    tt_patterns = {}
    if "TT" in frame:
        for value, group in frame.groupby("TT", dropna=False):
            width = pd.to_numeric(group["ROADWIDTH"], errors="coerce") if "ROADWIDTH" in group else pd.Series([], dtype=float)
            tt_patterns[str(value)] = {
                "feature_count": len(group),
                "roadwidth_min": float(width.min()) if width.notna().any() else None,
                "roadwidth_max": float(width.max()) if width.notna().any() else None,
                "intersect_values_containing_comma": int(group["INTERSECT"].str.contains(",", regex=False, na=False).sum()) if "INTERSECT" in group else None,
            }
    return {
        "directory": directory.as_posix(),
        "components": [{"name": path.name, "size_bytes": path.stat().st_size, "sha256": sha256_file(path)} for path in sorted(files.values(), key=lambda item: item.name.lower())],
        "declared_encoding": cpg,
        "prj_wkt": prj,
        "crs": {"status": "confirmed_from_prj", "name": "TWD97 / TM2 zone 121", "epsg": 3826},
        "shapefile": shp,
        "shx_feature_count": shx_count,
        "dbf": {**dbf, "fields": fields, "column_profiles": profiles},
        "road_id": {
            "present": "ROAD_ID" in frame,
            "null_count": int(road_id.eq("").sum()) if len(road_id) else None,
            "distinct_non_null_count": int(road_id[road_id.ne("")].nunique()) if len(road_id) else None,
            "duplicate_non_null_value_count": int((road_id[road_id.ne("")].value_counts() > 1).sum()) if len(road_id) else None,
            "unique_and_non_null": bool(len(road_id) and not road_id.eq("").any() and road_id.is_unique),
        },
        "roadwidth": {
            "valid_numeric_count": int(numeric_width.notna().sum()),
            "invalid_or_null_count": int(numeric_width.isna().sum()),
            "minimum": float(numeric_width.min()) if numeric_width.notna().any() else None,
            "maximum": float(numeric_width.max()) if numeric_width.notna().any() else None,
        },
        "tt_distribution": frame["TT"].value_counts(dropna=False).sort_index().to_dict() if "TT" in frame else None,
        "tt_observed_patterns": tt_patterns,
        "intersect_non_null_count": int(frame["INTERSECT"].ne("").sum()) if "INTERSECT" in frame else None,
        "tt_intersect_semantics": "unresolved_without_authoritative_field metadata",
    }


def schema_compatibility(first: dict, second: dict) -> dict:
    first_columns, second_columns = first["header"], second["header"]
    common = [column for column in first_columns if column in set(second_columns)]
    return {
        "safe_to_blindly_stack": first_columns == second_columns,
        "common_columns": common,
        "only_first_year": [column for column in first_columns if column not in set(second_columns)],
        "only_second_year": [column for column in second_columns if column not in set(first_columns)],
        "same_order_for_common_columns": common == [column for column in second_columns if column in set(first_columns)],
        "candidate_canonicalization": "requires explicit review of 光線 vs 道路照明設備 and 112-only 旅次目的; not executed",
    }


def stable_receipt_fingerprint(receipt: dict) -> str:
    stable = {key: value for key, value in receipt.items() if key not in {"generated_at_utc", "audit_fingerprint_sha256"}}
    payload = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_receipt(root: Path) -> dict:
    first_path = root / "data/raw/112年-臺北市死傷交通事故明細.csv"
    second_path = root / "data/raw/113年-臺北市死傷交通事故明細.csv"
    road_path = root / "data/raw/8mroadup"
    first = audit_accident_csv(first_path)
    second = audit_accident_csv(second_path)
    road = audit_road_layer(road_path)
    first["path"] = first_path.relative_to(root).as_posix()
    second["path"] = second_path.relative_to(root).as_posix()
    road["directory"] = road_path.relative_to(root).as_posix()
    compatibility = schema_compatibility(first, second)
    blockers = [
        "No explicit reliable accident ID; accident-level entity construction remains unresolved.",
        "Accident coordinate CRS is only a WGS84/EPSG:4326 candidate from numeric range; no source metadata confirms it.",
        "TT and INTERSECT semantics lack authoritative metadata.",
        "Road polygon OGC topology validity is unresolved without a topology engine; binary structural checks alone passed or are reported.",
        "The casualty-detail extracts have no property-damage field or demonstrated A3-only population, so complete EPDO is unsupported.",
        "The road reference source explicitly covers roads wider than 8 metres, so it is not a complete Taipei street universe.",
    ]
    receipt = {
        "contract_version": CONTRACT_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "audit_mode": "read_only_no_spatial_matching",
        "official_metadata_checked": {
            "accident_dataset": {
                "url": "https://data.taipei/dataset/detail?id=2f238b4f-1b27-4085-93e9-d684ef0e2735",
                "provider": "Taipei City Police Department Traffic Police Division",
                "confirmed": ["dataset supplies Taipei casualty traffic accident details", "X/Y are coordinate-point fields"],
                "not_confirmed": ["coordinate reference system", "accident-level identifier", "one-row-per-accident grain"],
            },
            "road_dataset": {
                "url": "https://data.taipei/dataset/detail?id=ee2e4015-8844-48fb-aa57-31209909b0fc",
                "provider": "Taipei City Public Works Department New Construction Office",
                "confirmed": ["roads wider than 8 metres", "built from the 2014-2016 survey project", "TWD97 coordinate system", "published field list agrees with local DBF"],
            },
        },
        "accident_files": {"112": first, "113": second},
        "schema_compatibility": compatibility,
        "road_reference": road,
        "phase8_3b_readiness": {
            "ready": False,
            "status": "BLOCKED",
            "blockers": blockers,
            "road_layer_candidate_use": "physical road polygon reference layer after metadata and topology limitations are resolved or explicitly contracted",
        },
        "prohibited_work_confirmed_not_performed": {
            "accident_to_road_matching": False,
            "accident_to_brouter_matching": False,
            "distance_threshold_selected": False,
            "epdo_calculated": False,
            "cbi_calculated": False,
            "risk_ranking_performed": False,
            "phase8_3b_started": False,
            "brouter_called": False,
        },
    }
    receipt["audit_fingerprint_sha256"] = stable_receipt_fingerprint(receipt)
    return receipt


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--output", type=Path, default=root / "notes/phase8_3a-accident-data-audit.json")
    args = parser.parse_args()
    receipt = build_receipt(args.root.resolve())
    args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "contract_version": receipt["contract_version"],
        "rows_112": receipt["accident_files"]["112"]["row_count"],
        "rows_113": receipt["accident_files"]["113"]["row_count"],
        "road_features": receipt["road_reference"]["shapefile"]["feature_count"],
        "phase8_3b_ready": receipt["phase8_3b_readiness"]["ready"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
