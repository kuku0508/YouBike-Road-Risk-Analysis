"""Phase 8.3C deterministic accident road-context finalization.

Road polygons provide physical context only.  This module intentionally has no
nearest-road fallback, distance threshold, BRouter join, or risk calculation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

try:
    from .validate_accident_road_reference import (
        SpatialContractError,
        atomic_json,
        atomic_parquet,
        load_and_validate_roads,
        load_locked_entities,
        sha256_file,
        stable_output_fingerprint as bounded_fingerprint,
    )
except ImportError:
    from validate_accident_road_reference import (
        SpatialContractError,
        atomic_json,
        atomic_parquet,
        load_and_validate_roads,
        load_locked_entities,
        sha256_file,
        stable_output_fingerprint as bounded_fingerprint,
    )


CONTRACT_VERSION = "accident-road-context-v1"
EXPECTED_ROWS = 46_586
EXPECTED_BOUNDED_RECEIPT_FINGERPRINT = "8fd98c25b967fb6fd5f1757688643eff8272fc8a00e1b503c41a3262e4cd1a70"
STATUS_VOCABULARY = (
    "contained_valid_road",
    "contained_blank_road_id",
    "outside_reference_coverage",
    "coordinate_unavailable",
    "contained_multiple",
)
EXPECTED_STATUS_COUNTS = {
    "contained_valid_road": 37_859,
    "contained_blank_road_id": 25,
    "outside_reference_coverage": 8_701,
    "coordinate_unavailable": 1,
    "contained_multiple": 0,
}
CRS_ASSUMPTION = "WGS84 geographic longitude/latitude operationally treated as EPSG:4326; transformed to EPSG:3826 for polygon coverage"
OUTPUT_COLUMNS = [
    "reconstructed_accident_id", "year", "event_datetime", "x_raw", "y_raw",
    "x_epsg3826", "y_epsg3826", "road_context_status", "road_id", "road_name",
    "town_name", "road_reference_feature_count", "crs_assumption",
    "source_accident_entity_fingerprint", "source_bounded_validation_fingerprint",
    "source_road_reference_fingerprint",
]


def stable_receipt_fingerprint(receipt: dict) -> str:
    stable = {key: value for key, value in receipt.items() if key not in {"generated_at_utc", "receipt_fingerprint_sha256"}}
    return hashlib.sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def road_reference_fingerprint(component_hashes: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(component_hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def assert_receipt_fingerprint(receipt: dict, expected: str) -> None:
    if stable_receipt_fingerprint(receipt) != receipt.get("receipt_fingerprint_sha256"):
        raise SpatialContractError("Phase 8.3B receipt fingerprint is internally inconsistent")
    if receipt["receipt_fingerprint_sha256"] != expected:
        raise SpatialContractError("Phase 8.3B locked receipt fingerprint mismatch")


def final_output_fingerprint(frame: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    for row in frame.sort_values("reconstructed_accident_id", kind="mergesort")[OUTPUT_COLUMNS].itertuples(index=False, name=None):
        values = []
        for value in row:
            if pd.isna(value):
                values.append(None)
            elif isinstance(value, float):
                if not math.isfinite(value):
                    raise SpatialContractError("non-finite canonical road-context value")
                values.append(format(value, ".12g"))
            elif hasattr(value, "item"):
                values.append(value.item())
            else:
                values.append(value)
        digest.update(json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def validate_bounded_receipt(root: Path) -> tuple[pd.DataFrame, dict]:
    receipt_path = root / "notes/phase8_3b-accident-road-reference-validation.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert_receipt_fingerprint(receipt, EXPECTED_BOUNDED_RECEIPT_FINGERPRINT)
    output = receipt["outputs"]
    path = root / output["validation_path"]
    if sha256_file(path) != output["validation_sha256"]:
        raise SpatialContractError("Phase 8.3B validation Parquet SHA-256 mismatch")
    frame = pd.read_parquet(path)
    if len(frame) != EXPECTED_ROWS or len(frame) != output["validation_rows"]:
        raise SpatialContractError("Phase 8.3B validation row-count mismatch")
    if bounded_fingerprint(frame) != output["validation_fingerprint_sha256"]:
        raise SpatialContractError("Phase 8.3B validation content fingerprint mismatch")
    if frame["reconstructed_accident_id"].isna().any() or not frame["reconstructed_accident_id"].is_unique:
        raise SpatialContractError("Phase 8.3B accident IDs are invalid")
    return frame, receipt


def classify_context(bounded_row: pd.Series, road_attribute: dict | None) -> tuple[str, str | None, str | None, str | None]:
    spatial_status = bounded_row["containment_status"]
    count = int(bounded_row["contained_polygon_count"])
    if spatial_status == "coordinate_unavailable":
        if count != 0:
            raise SpatialContractError("coordinate-unavailable row has polygon candidates")
        return "coordinate_unavailable", None, None, None
    if spatial_status == "contained_zero":
        if count != 0:
            raise SpatialContractError("contained-zero row has polygon candidates")
        return "outside_reference_coverage", None, None, None
    if spatial_status == "contained_multiple":
        if count <= 1:
            raise SpatialContractError("contained-multiple row lacks multiple candidates")
        return "contained_multiple", None, None, None
    if spatial_status != "contained_unique" or count != 1 or road_attribute is None:
        raise SpatialContractError(f"unsupported spatial state: {spatial_status!r}")
    road_id = road_attribute["road_id"] or None
    road_name = road_attribute["road_name"] or None
    town_name = road_attribute["town_name"] or None
    if road_id is None:
        return "contained_blank_road_id", None, road_name, town_name
    return "contained_valid_road", road_id, road_name, town_name


def candidate_feature_index(bounded_row: pd.Series) -> int | None:
    indexes = json.loads(bounded_row["candidate_feature_indexes_json"])
    count = int(bounded_row["contained_polygon_count"])
    if len(indexes) != count:
        raise SpatialContractError("candidate feature-index count mismatch")
    return int(indexes[0]) if count == 1 else None


def finalize_context(
    entities: pd.DataFrame,
    bounded: pd.DataFrame,
    road_attributes: list[dict],
    *,
    entity_fingerprint: str,
    bounded_validation_fingerprint: str,
    road_fingerprint: str,
) -> pd.DataFrame:
    entity_ids = set(entities["reconstructed_accident_id"])
    bounded_ids = set(bounded["reconstructed_accident_id"])
    if entity_ids != bounded_ids or len(entity_ids) != len(entities) or len(bounded_ids) != len(bounded):
        raise SpatialContractError("reconstructed accident ID set mismatch")
    entity_lookup = entities.set_index("reconstructed_accident_id")
    if not entity_lookup.index.is_unique:
        raise SpatialContractError("source accident IDs are not unique")
    rows = []
    for bounded_row in bounded.sort_values("reconstructed_accident_id", kind="mergesort").itertuples(index=False):
        series = pd.Series(bounded_row._asdict())
        feature_index = candidate_feature_index(series)
        road_attribute = road_attributes[feature_index] if feature_index is not None else None
        status, road_id, road_name, town_name = classify_context(series, road_attribute)
        entity = entity_lookup.loc[bounded_row.reconstructed_accident_id]
        spatial_available = status != "coordinate_unavailable"
        rows.append({
            "reconstructed_accident_id": bounded_row.reconstructed_accident_id,
            "year": int(entity["year"]),
            "event_datetime": entity["event_datetime"],
            "x_raw": bounded_row.x_raw if spatial_available else None,
            "y_raw": bounded_row.y_raw if spatial_available else None,
            "x_epsg3826": bounded_row.x_epsg3826 if spatial_available else None,
            "y_epsg3826": bounded_row.y_epsg3826 if spatial_available else None,
            "road_context_status": status,
            "road_id": road_id,
            "road_name": road_name,
            "town_name": town_name,
            "road_reference_feature_count": int(bounded_row.contained_polygon_count),
            "crs_assumption": CRS_ASSUMPTION,
            "source_accident_entity_fingerprint": entity_fingerprint,
            "source_bounded_validation_fingerprint": bounded_validation_fingerprint,
            "source_road_reference_fingerprint": road_fingerprint,
        })
    result = pd.DataFrame(rows, columns=OUTPUT_COLUMNS).sort_values("reconstructed_accident_id", kind="mergesort").reset_index(drop=True)
    validate_final_context(result, entity_ids)
    return result


def validate_final_context(
    frame: pd.DataFrame,
    expected_ids: set[str],
    *,
    expected_rows: int = EXPECTED_ROWS,
    expected_counts: dict[str, int] = EXPECTED_STATUS_COUNTS,
) -> dict[str, int]:
    if len(frame) != expected_rows or frame["reconstructed_accident_id"].isna().any() or not frame["reconstructed_accident_id"].is_unique:
        raise SpatialContractError("canonical row or ID conservation failed")
    if set(frame["reconstructed_accident_id"]) != expected_ids:
        raise SpatialContractError("canonical accident ID set differs from source")
    unknown = set(frame["road_context_status"]) - set(STATUS_VOCABULARY)
    if unknown:
        raise SpatialContractError(f"unknown road-context status: {unknown}")
    counts = {status: int((frame["road_context_status"] == status).sum()) for status in STATUS_VOCABULARY}
    if sum(counts.values()) != len(frame):
        raise SpatialContractError("status conservation failed")
    if counts != expected_counts:
        raise SpatialContractError(f"locked status-count mismatch: {counts}")
    valid = frame["road_context_status"] == "contained_valid_road"
    blank = frame["road_context_status"] == "contained_blank_road_id"
    no_context = frame["road_context_status"].isin(["outside_reference_coverage", "coordinate_unavailable", "contained_multiple"])
    if frame.loc[valid, "road_id"].isna().any() or frame.loc[valid, "road_id"].eq("").any():
        raise SpatialContractError("valid road context lacks ROAD_ID")
    if frame.loc[blank | no_context, "road_id"].notna().any():
        raise SpatialContractError("non-identifiable status received ROAD_ID")
    if frame.loc[no_context, ["road_name", "town_name"]].notna().any().any():
        raise SpatialContractError("non-contained status received road metadata")
    unavailable = frame["road_context_status"] == "coordinate_unavailable"
    if frame.loc[unavailable, ["x_raw", "y_raw", "x_epsg3826", "y_epsg3826"]].notna().any().any():
        raise SpatialContractError("coordinate-unavailable row received spatial values")
    return counts


def run(root: Path, output_path: Path, receipt_path: Path) -> dict:
    entities, entity_receipt = load_locked_entities(root)
    bounded, bounded_receipt = validate_bounded_receipt(root)
    _, road_attributes, road_audit = load_and_validate_roads(root)
    if road_audit["component_hashes"] != bounded_receipt["road_reference"]["component_hashes"]:
        raise SpatialContractError("road source hashes differ from Phase 8.3B")
    road_fingerprint = road_reference_fingerprint(road_audit["component_hashes"])
    entity_fp = entity_receipt["outputs"]["entity_fingerprint_sha256"]
    bounded_fp = bounded_receipt["outputs"]["validation_fingerprint_sha256"]
    result = finalize_context(
        entities, bounded, road_attributes,
        entity_fingerprint=entity_fp,
        bounded_validation_fingerprint=bounded_fp,
        road_fingerprint=road_fingerprint,
    )
    counts = validate_final_context(result, set(entities["reconstructed_accident_id"]))
    fingerprint = final_output_fingerprint(result)
    atomic_parquet(output_path, result)
    reread = pd.read_parquet(output_path)
    if final_output_fingerprint(reread) != fingerprint:
        raise SpatialContractError("canonical Parquet reread fingerprint mismatch")
    receipt = {
        "contract_version": CONTRACT_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "locked_inputs": {
            "phase8_3a2_entity_path": entity_receipt["outputs"]["entity_path"],
            "phase8_3a2_entity_fingerprint": entity_fp,
            "phase8_3a2_entity_sha256": entity_receipt["outputs"]["entity_sha256"],
            "phase8_3b_validation_path": bounded_receipt["outputs"]["validation_path"],
            "phase8_3b_validation_fingerprint": bounded_fp,
            "phase8_3b_validation_sha256": bounded_receipt["outputs"]["validation_sha256"],
            "phase8_3b_receipt_fingerprint": bounded_receipt["receipt_fingerprint_sha256"],
            "road_component_hashes": road_audit["component_hashes"],
            "road_reference_fingerprint": road_fingerprint,
        },
        "population": {
            "canonical_accident_count": len(result),
            "spatially_evaluable_count": int((result["road_context_status"] != "coordinate_unavailable").sum()),
            "status_counts": counts,
            "status_percentages_of_all_accidents": {status: count / len(result) for status, count in counts.items()},
            "status_conservation_exact": sum(counts.values()) == len(result),
            "reconstructed_accident_id_set_equal": set(result["reconstructed_accident_id"]) == set(entities["reconstructed_accident_id"]),
            "valid_road_id_context_coverage": counts["contained_valid_road"] / len(result),
        },
        "policy": {
            "status_vocabulary": list(STATUS_VOCABULARY),
            "direct_polygon_coverage_required": True,
            "valid_nonblank_road_id_required_for_identifiable_context": True,
            "nearest_road_fallback": "disabled",
            "distance_threshold": None,
            "road_name_as_identifier": False,
            "contained_multiple_tie_break": "disabled",
            "tt_intersect_use": "UNRESOLVED_NOT_USED",
        },
        "crs": {
            "road_crs_fact": "EPSG:3826",
            "accident_crs_status": "RECONSTRUCTION_ASSUMPTION_NOT_SOURCE_METADATA_FACT",
            "accident_crs_assumption": CRS_ASSUMPTION,
        },
        "limitations": {
            "road_reference_scope": "official Road.shp contains roads wider than 8 metres and is not the complete Taipei road universe",
            "outside_reference_semantics": "not covered by the study's >8m official road-polygon reference; not an invalid or off-road accident classification",
            "layer_roles": "Road.shp provides accident road context; BRouter directed segments remain the bicycle-flow estimation layer",
        },
        "output": {
            "path": output_path.relative_to(root).as_posix(),
            "row_count": len(result),
            "schema": OUTPUT_COLUMNS,
            "fingerprint_sha256": fingerprint,
            "parquet_sha256": sha256_file(output_path),
            "sorted_by": "reconstructed_accident_id",
        },
        "readiness": {
            "phase8_4": "READY_WITH_FORMAL_ROAD_CONTEXT_STATES_AND_DISCLOSED_REFERENCE_LIMITATIONS",
            "phase8_4_not_started": True,
        },
        "prohibited_work_confirmed_not_performed": {
            "nearest_road_assignment": False,
            "distance_threshold_selected": False,
            "road_name_text_matching": False,
            "address_geocoding": False,
            "brouter_candidate_search": False,
            "brouter_segment_assignment": False,
            "phase8_2_flow_join": False,
            "epdo_calculated": False,
            "cbi_calculated": False,
            "risk_analysis_started": False,
            "phase8_4_started": False,
        },
    }
    receipt["receipt_fingerprint_sha256"] = stable_receipt_fingerprint(receipt)
    atomic_json(receipt_path, receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    output = (args.output or root / "data/processed/accidents/accident_road_context_2023_2024.parquet").resolve()
    receipt = (args.receipt or root / "notes/phase8_3c-accident-road-context.json").resolve()
    result = run(root, output, receipt)
    print(json.dumps({"rows": result["population"]["canonical_accident_count"], "status_counts": result["population"]["status_counts"], "phase8_4": result["readiness"]["phase8_4"], "fingerprint": result["receipt_fingerprint_sha256"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
