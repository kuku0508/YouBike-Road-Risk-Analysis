"""Phase 8.3B accident-to-road reference coverage validation.

This module audits spatial relationships only.  It never assigns a ROAD_ID,
selects a distance threshold, or joins BRouter flow.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import shapefile
from pyproj import CRS, Transformer
from shapely import is_valid_reason
from shapely.geometry import Point, shape
from shapely.strtree import STRtree

try:
    from .reconstruct_accident_entities import dataframe_fingerprint
except ImportError:
    from reconstruct_accident_entities import dataframe_fingerprint


CONTRACT_VERSION = "accident-road-reference-validation-v1"
ACCIDENT_EXPECTED_ROWS = 46_586
ROAD_EXPECTED_FEATURES = 13_419
ROAD_EXPECTED_EPSG = 3826
ENTITY_COLUMNS = [
    "reconstructed_accident_id", "year", "event_datetime", "spot_location_raw",
    "spot_x_raw", "spot_y_raw", "handling_type", "party_record_count",
    "death_count", "death_2_30_day_count", "injury_count", "severity_missing",
    "party_sequence_conflict", "match_status", "match_method",
]
OUTPUT_COLUMNS = [
    "reconstructed_accident_id", "year", "x_raw", "y_raw", "x_epsg3826",
    "y_epsg3826", "containment_status", "contained_polygon_count",
    "contained_valid_road_id_count", "contained_distinct_valid_road_id_count",
    "contained_blank_road_id_count", "interior_polygon_count",
    "boundary_polygon_count", "candidate_road_ids_json", "candidate_road_names_json",
    "candidate_feature_indexes_json", "candidate_tt_values_json",
    "candidate_intersect_values_json", "nearest_distance_m",
    "second_nearest_distance_m", "distance_gap_m", "nearest_candidate_count",
]
RADII_M = (1, 3, 5, 10, 20, 30, 50)


class SpatialContractError(RuntimeError):
    """A locked input or spatial invariant failed."""


def require_crs_epsg(crs: CRS, expected: int = ROAD_EXPECTED_EPSG) -> None:
    if crs.to_epsg() != expected:
        raise SpatialContractError(f"road CRS mismatch: {crs.to_epsg()}")


def validate_geometry_gate(geometries: list, attributes: list[dict]) -> None:
    invalid = []
    for index, geometry in enumerate(geometries):
        if geometry.is_empty or geometry.geom_type != "Polygon" or not geometry.is_valid:
            invalid.append({
                "feature_index": index,
                "road_id": attributes[index].get("road_id", ""),
                "geometry_type": geometry.geom_type,
                "is_empty": geometry.is_empty,
                "validity_reason": is_valid_reason(geometry),
            })
    if invalid:
        raise SpatialContractError(f"road OGC validity gate failed: {invalid[:10]}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def atomic_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), temporary, compression="zstd")
    reread = pq.read_table(temporary).to_pandas()
    if len(reread) != len(frame) or list(reread.columns) != list(frame.columns):
        temporary.unlink(missing_ok=True)
        raise SpatialContractError("Parquet round-trip validation failed")
    os.replace(temporary, path)


def canonical_json_list(values: Iterable[str]) -> str:
    return json.dumps(sorted(set(str(value) for value in values)), ensure_ascii=False, separators=(",", ":"))


def stable_output_fingerprint(frame: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    for row in frame.sort_values("reconstructed_accident_id", kind="mergesort")[OUTPUT_COLUMNS].itertuples(index=False, name=None):
        values = []
        for value in row:
            if pd.isna(value):
                values.append(None)
            elif isinstance(value, float):
                if not math.isfinite(value):
                    raise SpatialContractError("non-finite output value")
                values.append(format(value, ".12g"))
            elif hasattr(value, "item"):
                values.append(value.item())
            else:
                values.append(value)
        digest.update(json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def load_locked_entities(root: Path) -> tuple[pd.DataFrame, dict]:
    receipt_path = root / "notes/phase8_3a2-accident-entity-reconstruction.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    output = receipt["outputs"]
    path = root / output["entity_path"]
    if sha256_file(path) != output["entity_sha256"]:
        raise SpatialContractError("accident entity Parquet SHA-256 mismatch")
    frame = pd.read_parquet(path)
    if len(frame) != ACCIDENT_EXPECTED_ROWS or len(frame) != output["entity_rows"]:
        raise SpatialContractError("accident entity row-count mismatch")
    if list(frame.columns) != ENTITY_COLUMNS:
        raise SpatialContractError("accident entity schema mismatch")
    ids = frame["reconstructed_accident_id"]
    if ids.isna().any() or not ids.is_unique or not ids.str.startswith("reconstructed_accident_").all():
        raise SpatialContractError("invalid reconstructed accident IDs")
    if set(frame["match_status"]) != {"exact_1to1"}:
        raise SpatialContractError("entity input contains non-accepted match status")
    fingerprint = dataframe_fingerprint(frame.fillna(""), ENTITY_COLUMNS)
    if fingerprint != output["entity_fingerprint_sha256"]:
        raise SpatialContractError("accident entity content fingerprint mismatch")
    return frame.sort_values("reconstructed_accident_id", kind="mergesort").reset_index(drop=True), receipt


def load_and_validate_roads(root: Path) -> tuple[list, list[dict], dict]:
    audit = json.loads((root / "notes/phase8_3a-accident-data-audit.json").read_text(encoding="utf-8"))
    road_audit = audit["road_reference"]
    directory = root / road_audit["directory"]
    expected_hashes = {item["name"]: item["sha256"] for item in road_audit["components"]}
    required = ("Road.shp", "Road.shx", "Road.dbf", "Road.prj", "Road.cpg")
    missing = [name for name in required if not (directory / name).is_file()]
    if missing:
        raise SpatialContractError(f"missing Shapefile components: {missing}")
    for name, expected in expected_hashes.items():
        if sha256_file(directory / name) != expected:
            raise SpatialContractError(f"road component hash mismatch: {name}")

    crs = CRS.from_wkt((directory / "Road.prj").read_text(encoding="utf-8"))
    require_crs_epsg(crs)

    reader = shapefile.Reader(str(directory / "Road.shp"), encoding="utf-8")
    field_names = [field[0] for field in reader.fields[1:]]
    if not {"ROAD_ID", "ROADNAME", "TT", "INTERSECT"}.issubset(field_names):
        raise SpatialContractError("road DBF lacks required QA fields")
    geometries = []
    attributes = []
    type_counts = Counter()
    for index, shape_record in enumerate(reader.iterShapeRecords()):
        geometry = shape(shape_record.shape.__geo_interface__)
        record = dict(zip(field_names, list(shape_record.record)))
        geometries.append(geometry)
        attributes.append({
            "feature_index": index,
            "road_id": str(record.get("ROAD_ID") or "").strip(),
            "road_name": str(record.get("ROADNAME") or "").strip(),
            "town_name": str(record.get("TOWNNAME") or "").strip(),
            "tt": str(record.get("TT") if record.get("TT") is not None else "").strip(),
            "intersect": str(record.get("INTERSECT") or "").strip(),
        })
        type_counts[geometry.geom_type] += 1
    if len(geometries) != ROAD_EXPECTED_FEATURES:
        raise SpatialContractError(f"road feature count mismatch: {len(geometries)}")
    validate_geometry_gate(geometries, attributes)
    blank = sum(not item["road_id"] for item in attributes)
    valid_ids = [item["road_id"] for item in attributes if item["road_id"]]
    if len(valid_ids) != len(set(valid_ids)):
        raise SpatialContractError("duplicate nonblank ROAD_ID")
    return geometries, attributes, {
        "directory": road_audit["directory"],
        "component_hashes": expected_hashes,
        "feature_count": len(geometries),
        "crs": crs.to_string(),
        "epsg": crs.to_epsg(),
        "geometry_type_counts": dict(sorted(type_counts.items())),
        "ogc_valid_count": len(geometries),
        "ogc_invalid_count": 0,
        "empty_geometry_count": 0,
        "valid_road_id_count": len(valid_ids),
        "blank_road_id_count": blank,
    }


def nearest_two(point: Point, tree: STRtree, geometries: list) -> tuple[float, float, int]:
    first_index = int(tree.nearest(point))
    first_distance = float(point.distance(geometries[first_index]))
    radius = max(first_distance * 2.0, 1.0)
    candidate_indexes: set[int] = set()
    second = math.inf
    for _ in range(32):
        candidate_indexes.update(int(index) for index in tree.query(point.buffer(radius).envelope))
        distances = sorted((float(point.distance(geometries[index])), index) for index in candidate_indexes)
        if len(distances) >= 2:
            second = distances[1][0]
            if radius >= second:
                break
        radius *= 2.0
    if not math.isfinite(second):
        raise SpatialContractError("could not establish second-nearest road polygon")
    distances = sorted((float(point.distance(geometries[index])), index) for index in candidate_indexes)
    nearest = distances[0][0]
    second = distances[1][0]
    tie_count = sum(math.isclose(distance, nearest, abs_tol=1e-9, rel_tol=0.0) for distance, _ in distances)
    return nearest, second, tie_count


def classify_point(point: Point, tree: STRtree, geometries: list, attributes: list[dict]) -> dict:
    bbox_candidates = sorted(int(index) for index in tree.query(point))
    covered = [index for index in bbox_candidates if geometries[index].covers(point)]
    covered.sort(key=lambda index: (attributes[index]["road_id"], attributes[index]["road_name"], index))
    if covered:
        selected = [attributes[index] for index in covered]
        valid_ids = [item["road_id"] for item in selected if item["road_id"]]
        boundary_count = sum(geometries[index].boundary.covers(point) for index in covered)
        interior_count = sum(geometries[index].contains(point) for index in covered)
        return {
            "containment_status": "contained_unique" if len(covered) == 1 else "contained_multiple",
            "contained_polygon_count": len(covered),
            "contained_valid_road_id_count": len(valid_ids),
            "contained_distinct_valid_road_id_count": len(set(valid_ids)),
            "contained_blank_road_id_count": sum(not item["road_id"] for item in selected),
            "interior_polygon_count": int(interior_count),
            "boundary_polygon_count": int(boundary_count),
            "candidate_road_ids_json": canonical_json_list(valid_ids),
            "candidate_road_names_json": canonical_json_list(item["road_name"] for item in selected if item["road_name"]),
            "candidate_feature_indexes_json": json.dumps(sorted(covered), separators=(",", ":")),
            "candidate_tt_values_json": canonical_json_list(item["tt"] for item in selected if item["tt"]),
            "candidate_intersect_values_json": canonical_json_list(item["intersect"] for item in selected if item["intersect"]),
            "nearest_distance_m": None,
            "second_nearest_distance_m": None,
            "distance_gap_m": None,
            "nearest_candidate_count": None,
        }
    nearest, second, tie_count = nearest_two(point, tree, geometries)
    return {
        "containment_status": "contained_zero",
        "contained_polygon_count": 0,
        "contained_valid_road_id_count": 0,
        "contained_distinct_valid_road_id_count": 0,
        "contained_blank_road_id_count": 0,
        "interior_polygon_count": 0,
        "boundary_polygon_count": 0,
        "candidate_road_ids_json": "[]",
        "candidate_road_names_json": "[]",
        "candidate_feature_indexes_json": "[]",
        "candidate_tt_values_json": "[]",
        "candidate_intersect_values_json": "[]",
        "nearest_distance_m": nearest,
        "second_nearest_distance_m": second,
        "distance_gap_m": second - nearest,
        "nearest_candidate_count": tie_count,
    }


def coordinate_unavailable_relationship() -> dict:
    return {
        "containment_status": "coordinate_unavailable",
        "contained_polygon_count": 0,
        "contained_valid_road_id_count": 0,
        "contained_distinct_valid_road_id_count": 0,
        "contained_blank_road_id_count": 0,
        "interior_polygon_count": 0,
        "boundary_polygon_count": 0,
        "candidate_road_ids_json": "[]",
        "candidate_road_names_json": "[]",
        "candidate_feature_indexes_json": "[]",
        "candidate_tt_values_json": "[]",
        "candidate_intersect_values_json": "[]",
        "nearest_distance_m": None,
        "second_nearest_distance_m": None,
        "distance_gap_m": None,
        "nearest_candidate_count": None,
    }


def validate_spatial_relationships(entities: pd.DataFrame, geometries: list, attributes: list[dict]) -> pd.DataFrame:
    transformer = Transformer.from_crs(4326, ROAD_EXPECTED_EPSG, always_xy=True)
    tree = STRtree(geometries)
    rows = []
    for item in entities.itertuples(index=False):
        if pd.isna(item.spot_x_raw) or pd.isna(item.spot_y_raw) or str(item.spot_x_raw).strip() == "" or str(item.spot_y_raw).strip() == "":
            rows.append({
                "reconstructed_accident_id": item.reconstructed_accident_id,
                "year": int(item.year), "x_raw": item.spot_x_raw, "y_raw": item.spot_y_raw,
                "x_epsg3826": None, "y_epsg3826": None,
                **coordinate_unavailable_relationship(),
            })
            continue
        longitude = float(item.spot_x_raw)
        latitude = float(item.spot_y_raw)
        if not (119.0 <= longitude <= 123.0 and 21.0 <= latitude <= 26.0):
            raise SpatialContractError(f"EPSG:4326 assumption range gate failed: {item.reconstructed_accident_id}")
        x, y = transformer.transform(longitude, latitude)
        if not (math.isfinite(x) and math.isfinite(y)):
            raise SpatialContractError("CRS transformation produced non-finite coordinate")
        relationship = classify_point(Point(x, y), tree, geometries, attributes)
        rows.append({
            "reconstructed_accident_id": item.reconstructed_accident_id,
            "year": int(item.year),
            "x_raw": item.spot_x_raw,
            "y_raw": item.spot_y_raw,
            "x_epsg3826": x,
            "y_epsg3826": y,
            **relationship,
        })
    result = pd.DataFrame(rows, columns=OUTPUT_COLUMNS).sort_values("reconstructed_accident_id", kind="mergesort").reset_index(drop=True)
    if len(result) != len(entities) or result["reconstructed_accident_id"].duplicated().any():
        raise SpatialContractError("one-row-per-accident conservation failed")
    return result


def numeric_summary(values: pd.Series) -> dict:
    series = pd.to_numeric(values, errors="raise").astype(float)
    quantiles = series.quantile([0.5, 0.75, 0.9, 0.95, 0.975, 0.99])
    return {
        "count": int(len(series)), "min": float(series.min()), "max": float(series.max()),
        "mean": float(series.mean()), "median": float(series.median()),
        "p50": float(quantiles.loc[0.5]), "p75": float(quantiles.loc[0.75]),
        "p90": float(quantiles.loc[0.9]), "p95": float(quantiles.loc[0.95]),
        "p97_5": float(quantiles.loc[0.975]), "p99": float(quantiles.loc[0.99]),
    }


def coverage_summary(frame: pd.DataFrame) -> dict:
    total = len(frame)
    counts = frame["containment_status"].value_counts().to_dict()
    unavailable = int(counts.get("coordinate_unavailable", 0))
    spatially_evaluable = total - unavailable
    zero = frame[frame["containment_status"] == "contained_zero"]
    unique = frame[frame["containment_status"] == "contained_unique"]
    multiple = frame[frame["containment_status"] == "contained_multiple"]
    radius = {}
    for metres in RADII_M:
        count = int((zero["nearest_distance_m"] <= metres).sum())
        radius[str(metres)] = {"count": count, "percentage_of_contained_zero": count / len(zero) if len(zero) else 0.0, "percentage_of_all_accidents": count / total}
    candidate_distribution = {str(int(key)): int(value) for key, value in multiple["contained_polygon_count"].value_counts().sort_index().items()}
    grouped_distribution = {
        "2": int((multiple["contained_polygon_count"] == 2).sum()),
        "3": int((multiple["contained_polygon_count"] == 3).sum()),
        "4_plus": int((multiple["contained_polygon_count"] >= 4).sum()),
    }
    return {
        "total": total,
        "spatially_evaluable": spatially_evaluable,
        "coordinate_unavailable": {"count": unavailable, "percentage_of_all_accidents": unavailable / total},
        "containment": {status: {"count": int(counts.get(status, 0)), "percentage_of_all_accidents": int(counts.get(status, 0)) / total, "percentage_of_spatially_evaluable": int(counts.get(status, 0)) / spatially_evaluable if spatially_evaluable else 0.0} for status in ("contained_unique", "contained_multiple", "contained_zero")},
        "unique_with_valid_road_id": {"count": int((unique["contained_valid_road_id_count"] == 1).sum()), "percentage": float((unique["contained_valid_road_id_count"] == 1).sum() / total)},
        "unique_with_blank_road_id": {"count": int((unique["contained_blank_road_id_count"] == 1).sum()), "percentage": float((unique["contained_blank_road_id_count"] == 1).sum() / total)},
        "multiple_candidate_count_distribution": candidate_distribution,
        "multiple_candidate_count_grouped": grouped_distribution,
        "multiple_with_interior_overlap": int((multiple["interior_polygon_count"] >= 2).sum()),
        "multiple_with_any_boundary_hit": int((multiple["boundary_polygon_count"] > 0).sum()),
        "multiple_with_shared_boundary_hit": int((multiple["boundary_polygon_count"] >= 2).sum()),
        "contained_zero_radius_sensitivity_m": radius,
        "nearest_distance_m": numeric_summary(zero["nearest_distance_m"]),
        "second_nearest_distance_m": numeric_summary(zero["second_nearest_distance_m"]),
        "distance_gap_m": numeric_summary(zero["distance_gap_m"]),
        "contained_zero_equal_nearest_ties": int((zero["nearest_candidate_count"] > 1).sum()),
    }


def deterministic_qa_sample(frame: pd.DataFrame) -> pd.DataFrame:
    zero = frame[frame["containment_status"] == "contained_zero"]
    selectors = [
        ("contained_unique", frame[frame["containment_status"] == "contained_unique"].sort_values("reconstructed_accident_id")),
        ("contained_multiple", frame[frame["containment_status"] == "contained_multiple"].sort_values("reconstructed_accident_id")),
        ("contained_zero_very_near_le_3m", zero[zero["nearest_distance_m"] <= 3].sort_values(["nearest_distance_m", "reconstructed_accident_id"])),
        ("contained_zero_medium_10_30m", zero[(zero["nearest_distance_m"] > 10) & (zero["nearest_distance_m"] <= 30)].sort_values(["nearest_distance_m", "reconstructed_accident_id"])),
        ("contained_zero_far_gt_50m", zero[zero["nearest_distance_m"] > 50].sort_values(["nearest_distance_m", "reconstructed_accident_id"], ascending=[False, True])),
        ("small_nearest_second_gap", zero.sort_values(["distance_gap_m", "reconstructed_accident_id"])),
        ("large_nearest_second_gap", zero.sort_values(["distance_gap_m", "reconstructed_accident_id"], ascending=[False, True])),
        ("blank_road_id_candidate", frame[frame["contained_blank_road_id_count"] > 0].sort_values("reconstructed_accident_id")),
        ("coordinate_unavailable", frame[frame["containment_status"] == "coordinate_unavailable"].sort_values("reconstructed_accident_id")),
    ]
    pieces = []
    for category, candidates in selectors:
        sample = candidates.head(5).copy()
        sample.insert(0, "qa_category", category)
        pieces.append(sample)
    return pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame(columns=["qa_category", *OUTPUT_COLUMNS])


def run(root: Path, output_path: Path, qa_path: Path, receipt_path: Path) -> dict:
    entities, entity_receipt = load_locked_entities(root)
    geometries, attributes, road = load_and_validate_roads(root)
    result = validate_spatial_relationships(entities, geometries, attributes)
    summary = coverage_summary(result)
    qa = deterministic_qa_sample(result)
    output_fingerprint = stable_output_fingerprint(result)
    atomic_parquet(output_path, result)
    qa_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_qa = qa_path.with_suffix(qa_path.suffix + ".tmp")
    qa.to_csv(temporary_qa, index=False, encoding="utf-8", quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    os.replace(temporary_qa, qa_path)
    receipt = {
        "contract_version": CONTRACT_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "accident_entity_input": {
            "path": entity_receipt["outputs"]["entity_path"],
            "sha256": entity_receipt["outputs"]["entity_sha256"],
            "fingerprint_sha256": entity_receipt["outputs"]["entity_fingerprint_sha256"],
            "row_count": len(entities),
            "id_contract": entity_receipt["reconstructed_id_contract"],
        },
        "road_reference": road,
        "crs_contract": {
            "accident_source_assumption": "WGS84 geographic longitude/latitude operationally treated as EPSG:4326",
            "assumption_status": "RECONSTRUCTION_ASSUMPTION_NOT_SOURCE_METADATA_FACT",
            "target_crs": "EPSG:3826",
            "distance_unit": "metre",
        },
        "containment_contract": {
            "predicate": "polygon.covers(point)",
            "boundary_semantics": "boundary points are covered",
            "road_assignment_performed": False,
            "nearest_road_assignment_performed": False,
            "formal_distance_threshold_selected": False,
        },
        "coverage": summary,
        "outputs": {
            "validation_path": output_path.relative_to(root).as_posix(),
            "validation_rows": len(result),
            "validation_fingerprint_sha256": output_fingerprint,
            "validation_sha256": sha256_file(output_path),
            "qa_sample_path": qa_path.relative_to(root).as_posix(),
            "qa_sample_rows": len(qa),
            "qa_sample_sha256": sha256_file(qa_path),
        },
        "limitations": {
            "road_reference_scope": "official reference contains roads wider than 8 metres; it is not the complete Taipei road universe",
            "contained_zero_interpretation": "outside this reference coverage, not proof of accident error or off-road location",
            "coordinate_unavailable_interpretation": "accepted entity retained without spatial classification; no coordinate was invented",
            "tt_intersect_semantics": "UNRESOLVED; retained for QA only and never used for disambiguation",
            "road_name_use": "QA description only; never used as matching rule",
        },
        "readiness": {
            "phase8_3c": "READY_FOR_HUMAN_POLICY_DECISION_WITH_DISCLOSED_COVERAGE_LIMITATIONS",
            "unresolved_decisions": ["whether to use nearest-road fallback", "formal distance threshold", "multiple-polygon disambiguation rule", "treatment of outside-reference coverage"],
        },
        "prohibited_work_confirmed_not_performed": {
            "assigned_road_id": False, "nearest_road_selected": False,
            "distance_threshold_selected": False, "tt_intersect_disambiguation": False,
            "brouter_segment_matching": False, "phase8_2_flow_join": False,
            "epdo_calculated": False, "cbi_calculated": False,
            "risk_analysis_started": False, "phase8_3c_started": False,
        },
        "software": {"shapely": __import__("shapely").__version__, "pyproj": __import__("pyproj").__version__, "pyshp": shapefile.__version__},
    }
    stable = {key: value for key, value in receipt.items() if key not in {"generated_at_utc", "receipt_fingerprint_sha256"}}
    receipt["receipt_fingerprint_sha256"] = hashlib.sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    atomic_json(receipt_path, receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--qa", type=Path)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output or root / "data/interim/accidents/accident_road_reference_validation_2023_2024.parquet"
    qa = args.qa or root / "notes/phase8_3b-accident-road-reference-qa-sample.csv"
    receipt = args.receipt or root / "notes/phase8_3b-accident-road-reference-validation.json"
    result = run(root, output.resolve(), qa.resolve(), receipt.resolve())
    print(json.dumps({"accidents": result["accident_entity_input"]["row_count"], "containment": result["coverage"]["containment"], "phase8_3c": result["readiness"]["phase8_3c"], "fingerprint": result["receipt_fingerprint_sha256"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
