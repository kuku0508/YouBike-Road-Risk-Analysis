"""Phase 8.4A bounded accident-to-BRouter candidate validation.

This module deliberately produces diagnostics, not accident-to-segment assignments.
Flow weights are never read into candidate ranking or tie-breaking.
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

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pyproj import Transformer
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree

try:
    from .finalize_accident_road_context import final_output_fingerprint
    from .validate_accident_road_reference import (
        SpatialContractError, atomic_json, atomic_parquet, load_and_validate_roads,
        sha256_file, stable_output_fingerprint as bounded_fingerprint,
    )
except ImportError:
    from finalize_accident_road_context import final_output_fingerprint
    from validate_accident_road_reference import (
        SpatialContractError, atomic_json, atomic_parquet, load_and_validate_roads,
        sha256_file, stable_output_fingerprint as bounded_fingerprint,
    )

CONTRACT_VERSION = "accident-brouter-candidate-validation-v1"
DIRECTED_PATH = "data/processed/routing/directed_segment_usage_2023_2024.parquet"
ACCIDENT_PATH = "data/processed/accidents/accident_road_context_2023_2024.parquet"
BOUNDED_PATH = "data/interim/accidents/accident_road_reference_validation_2023_2024.parquet"
NEUTRAL_PATH = "data/interim/routing/neutral_brouter_microsegments_2023_2024.parquet"
OUTPUT_PATH = "data/interim/accidents/accident_brouter_candidate_validation_2023_2024.parquet"
EXPECTED_DIRECTED_SHA = "68d0dec6498b7734b6cd09c7f94ec20cfa8708de31cbdb898b4ad65a0288f8ad"
EXPECTED_DIRECTED_FP = "0925c99aa8f0022c953e09046bd7728d6a546cae6f28c81f68ccb5e35d6b2a04"
EXPECTED_ACCIDENT_SHA = "d64954bf04877776968f7eb8e8bf6755d96c2ea75019d292325234c2df75cfa3"
EXPECTED_ACCIDENT_FP = "186f751e3a33ff2db01e7e44abe3255fff1008de3e9aaeb35056dd541e6b9f5b"
EXPECTED_BOUNDED_SHA = "313bb429e594cd93ded17326f0a4fbfc191789252635bd7214a70b08eaed52ee"
DIRECTED_COLUMNS = ["from_lon_e6", "from_lat_e6", "to_lon_e6", "to_lat_e6",
                    "segment_traversal_count", "unique_route_count", "total_trip_weight",
                    "weekday_trip_weight", "holiday_trip_weight"]
OUTPUT_COLUMNS = [
    "reconstructed_accident_id", "road_context_status", "road_id", "road_name", "town_name",
    "global_nearest_segment_key", "global_nearest_distance_m", "global_second_nearest_segment_key", "global_second_distance_m",
    "global_distance_gap_m", "global_exact_tie_count", "global_near_gap_bin",
    "context_constraint_available", "context_candidate_count", "context_nearest_segment_key", "context_nearest_distance_m",
    "context_second_nearest_segment_key", "context_second_distance_m", "context_distance_gap_m", "context_exact_tie_count",
    "context_near_gap_bin", "global_context_same_nearest", "context_minus_global_distance_m",
    "context_feature_indexes_json", "diagnostic_status",
]


def stable_receipt_fingerprint(receipt: dict) -> str:
    stable = {k: v for k, v in receipt.items() if k not in {"generated_at_utc", "receipt_fingerprint_sha256"}}
    return hashlib.sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def segment_key(key: tuple[int, int, int, int]) -> str:
    return f"{key[0]},{key[1]}|{key[2]},{key[3]}"


def neutral_key(row) -> tuple[int, int, int, int]:
    a = (int(row.from_lon_e6), int(row.from_lat_e6)); b = (int(row.to_lon_e6), int(row.to_lat_e6))
    if a == b:
        raise SpatialContractError("zero-length directed segment")
    lo, hi = sorted((a, b))
    return lo[0], lo[1], hi[0], hi[1]


def directed_fingerprint(frame: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    ordered = frame.sort_values(DIRECTED_COLUMNS[:4], kind="mergesort")
    for row in ordered[DIRECTED_COLUMNS].itertuples(index=False, name=None):
        digest.update(("|".join(map(str, row)) + "\n").encode())
    return digest.hexdigest()


def build_neutral_segments(directed: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    if list(directed.columns) != DIRECTED_COLUMNS:
        raise SpatialContractError("Phase 8.2 directed segment schema mismatch")
    members: dict[tuple[int, int, int, int], list[tuple[int, int, int, int]]] = {}
    for row in directed.itertuples(index=False):
        key = neutral_key(row); members.setdefault(key, []).append(tuple(int(x) for x in row[:4]))
    rows = []
    multiplicity = Counter()
    for key in sorted(members):
        values = members[key]; multiplicity[len(values)] += 1
        if len(values) > 2 or len(set(values)) != len(values):
            raise SpatialContractError(f"unexpected neutral segment multiplicity: {segment_key(key)}")
        forward = key in values
        reverse_key = (key[2], key[3], key[0], key[1])
        reverse = reverse_key in values
        if len(values) == 2 and not (forward and reverse):
            raise SpatialContractError(f"two members are not reciprocal: {segment_key(key)}")
        rows.append({
            "physical_segment_key": segment_key(key), "a_lon_e6": key[0], "a_lat_e6": key[1],
            "b_lon_e6": key[2], "b_lat_e6": key[3], "has_forward_member": forward,
            "has_reverse_member": reverse,
            "directed_member_keys_json": json.dumps([f"{v[0]},{v[1]}->{v[2]},{v[3]}" for v in sorted(values)], separators=(",", ":")),
        })
    frame = pd.DataFrame(rows)
    return frame, {
        "directed_input_count": len(directed), "neutral_physical_segment_count": len(frame),
        "one_direction_only_count": multiplicity[1], "both_directions_count": multiplicity[2],
        "unexpected_gt2_multiplicity_count": sum(v for k, v in multiplicity.items() if k > 2),
        "directed_member_conservation": sum(k * v for k, v in multiplicity.items()) == len(directed),
    }


def neutral_geometries(neutral: pd.DataFrame) -> list[LineString]:
    transformer = Transformer.from_crs(4326, 3826, always_xy=True)
    geometries = []
    for row in neutral.itertuples(index=False):
        coords = [(row.a_lon_e6 / 1e6, row.a_lat_e6 / 1e6), (row.b_lon_e6 / 1e6, row.b_lat_e6 / 1e6)]
        if not all(math.isfinite(v) for p in coords for v in p):
            raise SpatialContractError("non-finite microdegree endpoint")
        xy = [transformer.transform(*p) for p in coords]
        line = LineString(xy)
        if line.is_empty or not line.is_valid or not math.isfinite(line.length) or line.length <= 0:
            raise SpatialContractError("invalid transformed neutral segment")
        geometries.append(line)
    return geometries


def gap_bin(gap: float | None) -> str | None:
    if gap is None or not math.isfinite(gap): return None
    for edge in (0.1, 0.5, 1.0, 2.0, 5.0):
        if gap <= edge: return f"<= {edge:g} m"
    return "> 5 m"


def candidate_profile(point: Point, geometries: list[LineString], keys: list[str], indexes: list[int]) -> dict:
    if not indexes:
        return {"key": None, "distance": None, "second_key": None, "second": None, "gap": None, "ties": 0, "gap_bin": None}
    distances = sorted((float(point.distance(geometries[i])), keys[i], i) for i in indexes)
    nearest = distances[0][0]
    ties = sum(math.isclose(d, nearest, abs_tol=1e-9, rel_tol=0.0) for d, _, _ in distances)
    second = distances[1][0] if len(distances) > 1 else None
    gap = None if second is None else second - nearest
    return {"key": distances[0][1], "distance": nearest, "second_key": distances[1][1] if len(distances)>1 else None, "second": second, "gap": gap, "ties": ties, "gap_bin": gap_bin(gap)}


def global_profile(point: Point, tree: STRtree, geometries: list[LineString], keys: list[str]) -> dict:
    first = int(tree.nearest(point)); first_distance = float(point.distance(geometries[first]))
    radius = max(1.0, first_distance + 1.0)
    indexes: set[int] = set()
    for _ in range(32):
        indexes.update(int(i) for i in tree.query(point.buffer(radius).envelope))
        distances = sorted(float(point.distance(geometries[i])) for i in indexes)
        if len(distances) >= 2 and radius >= distances[1]: break
        radius *= 2
    if len(indexes) < 2:
        raise SpatialContractError("could not establish global second-nearest segment")
    return candidate_profile(point, geometries, keys, sorted(indexes))


def numeric_summary(series: pd.Series) -> dict:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty: return {"count": 0}
    result = {"count": int(len(values)), "min": float(values.min()), "mean": float(values.mean()), "max": float(values.max())}
    for q, label in ((.5,"p50"),(.75,"p75"),(.9,"p90"),(.95,"p95"),(.975,"p97_5"),(.99,"p99")):
        result[label] = float(values.quantile(q))
    result["bins_le_m"] = {str(edge): int((values <= edge).sum()) for edge in (.5,1,2,3,5,10,20,30,50)}
    return result


def candidate_size_bins(values: pd.Series) -> dict:
    return {
        "0": int((values == 0).sum()), "1": int((values == 1).sum()), "2": int((values == 2).sum()),
        "3-5": int(values.between(3,5).sum()), "6-10": int(values.between(6,10).sum()),
        "11-20": int(values.between(11,20).sum()), ">20": int((values > 20).sum()),
    }


def categorical_counts(values: pd.Series) -> dict[str, int]:
    """Return JSON-safe deterministic counts, including an explicit null label."""
    normalized = values.where(values.notna(), "null").astype(str)
    return {str(key): int(value) for key, value in normalized.value_counts().sort_index().items()}


def validate_inputs(root: Path):
    p2 = json.loads((root / "notes/phase8_2-segment-usage-completion.json").read_text(encoding="utf-8"))
    directed_path = root / DIRECTED_PATH
    if p2["output_sha256"] != EXPECTED_DIRECTED_SHA or sha256_file(directed_path) != EXPECTED_DIRECTED_SHA:
        raise SpatialContractError("Phase 8.2 Parquet SHA mismatch")
    directed = pd.read_parquet(directed_path)
    if len(directed) != 149_234 or directed_fingerprint(directed) != EXPECTED_DIRECTED_FP:
        raise SpatialContractError("Phase 8.2 row count or fingerprint mismatch")
    p3 = json.loads((root / "notes/phase8_3c-accident-road-context.json").read_text(encoding="utf-8"))
    accident_path = root / ACCIDENT_PATH
    if p3["output"]["parquet_sha256"] != EXPECTED_ACCIDENT_SHA or sha256_file(accident_path) != EXPECTED_ACCIDENT_SHA:
        raise SpatialContractError("Phase 8.3C Parquet SHA mismatch")
    accidents = pd.read_parquet(accident_path)
    if len(accidents) != 46_586 or final_output_fingerprint(accidents) != EXPECTED_ACCIDENT_FP:
        raise SpatialContractError("Phase 8.3C row count or fingerprint mismatch")
    bounded_path = root / BOUNDED_PATH; bounded = pd.read_parquet(bounded_path)
    if sha256_file(bounded_path) != EXPECTED_BOUNDED_SHA or bounded_fingerprint(bounded) != p3["locked_inputs"]["phase8_3b_validation_fingerprint"]:
        raise SpatialContractError("Phase 8.3B bounded validation mismatch")
    return directed, accidents, bounded, p2, p3


def run_validation(accidents, bounded, neutral, geometries, road_geometries, road_attributes):
    keys = neutral["physical_segment_key"].tolist(); tree = STRtree(geometries)
    road_id_to_index = {}
    for a in road_attributes:
        if a["road_id"]:
            if a["road_id"] in road_id_to_index: raise SpatialContractError("ROAD_ID is not unique")
            road_id_to_index[a["road_id"]] = a["feature_index"]
    bounded_by_id = bounded.set_index("reconstructed_accident_id")
    context_cache: dict[int, list[int]] = {}
    def context_indexes(feature: int):
        if feature not in context_cache:
            context_cache[feature] = sorted(int(i) for i in tree.query(road_geometries[feature], predicate="intersects"))
        return context_cache[feature]
    rows = []
    for row in accidents.sort_values("reconstructed_accident_id", kind="mergesort").itertuples(index=False):
        base = {c: getattr(row, c) for c in ("reconstructed_accident_id","road_context_status","road_id","road_name","town_name")}
        if row.road_context_status == "coordinate_unavailable":
            rows.append({**base, **{c: None for c in OUTPUT_COLUMNS[5:-1]}, "diagnostic_status": "coordinate_unavailable_no_search"}); continue
        if row.road_context_status == "contained_multiple":
            raise SpatialContractError("contained_multiple requires an analyst policy before candidate validation")
        point = Point(float(row.x_epsg3826), float(row.y_epsg3826)); gp = global_profile(point, tree, geometries, keys)
        feature_indexes = []
        if row.road_context_status == "contained_valid_road":
            if row.road_id not in road_id_to_index: raise SpatialContractError("valid road context lacks unique polygon")
            feature_indexes = [road_id_to_index[row.road_id]]
        elif row.road_context_status == "contained_blank_road_id":
            feature_indexes = [int(x) for x in json.loads(bounded_by_id.loc[row.reconstructed_accident_id, "candidate_feature_indexes_json"])]
            if not feature_indexes: raise SpatialContractError("blank road context lacks stable feature identity")
        context = sorted(set(i for f in feature_indexes for i in context_indexes(f)))
        cp = candidate_profile(point, geometries, keys, context) if feature_indexes else candidate_profile(point, geometries, keys, [])
        same = None if not feature_indexes or cp["key"] is None else gp["key"] == cp["key"]
        delta = None if cp["distance"] is None else cp["distance"] - gp["distance"]
        rows.append({**base,
            "global_nearest_segment_key": gp["key"], "global_nearest_distance_m": gp["distance"],
            "global_second_nearest_segment_key": gp["second_key"], "global_second_distance_m": gp["second"], "global_distance_gap_m": gp["gap"],
            "global_exact_tie_count": gp["ties"], "global_near_gap_bin": gp["gap_bin"],
            "context_constraint_available": bool(feature_indexes), "context_candidate_count": len(context), "context_nearest_segment_key": cp["key"],
            "context_nearest_distance_m": cp["distance"], "context_second_distance_m": cp["second"],
            "context_second_nearest_segment_key": cp["second_key"],
            "context_distance_gap_m": cp["gap"], "context_exact_tie_count": cp["ties"],
            "context_near_gap_bin": cp["gap_bin"], "global_context_same_nearest": same,
            "context_minus_global_distance_m": delta,
            "context_feature_indexes_json": json.dumps(sorted(feature_indexes), separators=(",", ":")),
            "diagnostic_status": "global_and_context_candidates" if feature_indexes else "global_candidates_only",
        })
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS), tree


def brute_force_check(frame, accidents, geometries, keys, sample_size=200):
    evaluable = accidents[accidents.road_context_status != "coordinate_unavailable"].sort_values("reconstructed_accident_id")
    sample = evaluable.iloc[::max(1, len(evaluable)//sample_size)].head(sample_size)
    indexed = frame.set_index("reconstructed_accident_id")
    mismatches = []
    for row in sample.itertuples(index=False):
        p = Point(row.x_epsg3826, row.y_epsg3826); brute = candidate_profile(p, geometries, keys, list(range(len(keys))))
        got = indexed.loc[row.reconstructed_accident_id]
        if brute["key"] != got.global_nearest_segment_key or not math.isclose(brute["distance"], got.global_nearest_distance_m, abs_tol=1e-9):
            mismatches.append(row.reconstructed_accident_id)
    if mismatches: raise SpatialContractError(f"indexed/brute-force mismatch: {mismatches[:5]}")
    return {"sample_size": len(sample), "mismatch_count": 0, "exact_match": True}


def output_fingerprint(frame):
    digest = hashlib.sha256()
    for row in frame.sort_values("reconstructed_accident_id")[OUTPUT_COLUMNS].itertuples(index=False, name=None):
        values=[]
        for v in row:
            if v is None or pd.isna(v): values.append(None)
            elif isinstance(v, float): values.append(format(v, ".12g"))
            elif hasattr(v,"item"): values.append(v.item())
            else: values.append(v)
        digest.update((json.dumps(values,ensure_ascii=False,separators=(",",":"))+"\n").encode())
    return digest.hexdigest()


def neutral_fingerprint(frame):
    digest=hashlib.sha256()
    for row in frame.sort_values("physical_segment_key").itertuples(index=False,name=None):
        digest.update((json.dumps(list(row),ensure_ascii=False,separators=(",",":"))+"\n").encode())
    return digest.hexdigest()


def deterministic_qa(frame):
    picks=[]
    groups=[
        ("valid_same", (frame.road_context_status=="contained_valid_road") & (frame.global_context_same_nearest==True)),
        ("valid_different", (frame.road_context_status=="contained_valid_road") & (frame.global_context_same_nearest==False)),
        ("blank_context", frame.road_context_status=="contained_blank_road_id"),
        ("outside_global_only", frame.road_context_status=="outside_reference_coverage"),
        ("coordinate_unavailable", frame.road_context_status=="coordinate_unavailable"),
        ("exact_tie", frame.global_exact_tie_count.fillna(0)>1),
        ("near_tie_le_1m", frame.global_distance_gap_m.fillna(math.inf)<=1),
        ("far_global", frame.global_nearest_distance_m.fillna(-1)>50),
    ]
    for label, mask in groups:
        part=frame[mask].sort_values("reconstructed_accident_id").head(5).copy(); part.insert(0,"qa_category",label); picks.append(part)
    return pd.concat(picks,ignore_index=True)


def execute(root: Path, output: Path, neutral_output: Path, qa_path: Path, receipt_path: Path):
    directed, accidents, bounded, p2, p3 = validate_inputs(root)
    neutral, neutral_summary = build_neutral_segments(directed); geometries = neutral_geometries(neutral)
    roads, road_attributes, road_audit = load_and_validate_roads(root)
    result, _ = run_validation(accidents, bounded, neutral, geometries, roads, road_attributes)
    if len(result)!=len(accidents) or not result.reconstructed_accident_id.is_unique: raise SpatialContractError("one-row-per-accident invariant failed")
    brute = brute_force_check(result, accidents, geometries, neutral.physical_segment_key.tolist())
    atomic_parquet(neutral_output, neutral); atomic_parquet(output, result)
    qa=deterministic_qa(result); qa_path.parent.mkdir(parents=True,exist_ok=True); tmp=qa_path.with_suffix(qa_path.suffix+".tmp"); qa.to_csv(tmp,index=False,encoding="utf-8",quoting=csv.QUOTE_MINIMAL,lineterminator="\n"); os.replace(tmp,qa_path)
    valid=result[result.road_context_status=="contained_valid_road"]; blank=result[result.road_context_status=="contained_blank_road_id"]; outside=result[result.road_context_status=="outside_reference_coverage"]
    receipt={
        "contract_version": CONTRACT_VERSION, "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "locked_inputs": {"phase8_2_path":DIRECTED_PATH,"phase8_2_sha256":EXPECTED_DIRECTED_SHA,"phase8_2_fingerprint":EXPECTED_DIRECTED_FP,"phase8_3c_path":ACCIDENT_PATH,"phase8_3c_sha256":EXPECTED_ACCIDENT_SHA,"phase8_3c_fingerprint":EXPECTED_ACCIDENT_FP,"phase8_3b_bounded_sha256":EXPECTED_BOUNDED_SHA,"road_reference_fingerprint":p3["locked_inputs"]["road_reference_fingerprint"]},
        "population": {"accidents":len(result),"status_counts":result.road_context_status.value_counts().sort_index().to_dict(),"one_row_per_accident":True},
        "neutral_segments": neutral_summary,
        "crs_and_geometry": {"source_endpoint_unit":"integer microdegrees","source_crs":"EPSG:4326","target_crs":"EPSG:3826","distance_unit":"metre","segment_identity":"lexicographically ordered endpoint integer tuple","context_predicate":"LineString.intersects(road_polygon)"},
        "global_search": {"evaluable_accidents":int(result.global_nearest_distance_m.notna().sum()),"distance_m":numeric_summary(result.global_nearest_distance_m),"exact_tie_accidents":int((result.global_exact_tie_count.fillna(0)>1).sum()),"near_gap_bins":categorical_counts(result.global_near_gap_bin)},
        "road_context_search": {
            "contained_valid_road": {"count":len(valid),"same_nearest":int((valid.global_context_same_nearest==True).sum()),"same_nearest_rate":float((valid.global_context_same_nearest==True).mean()),"different_nearest":int((valid.global_context_same_nearest==False).sum()),"empty_candidate_set":int((valid.context_candidate_count==0).sum()),"global_distance_m":numeric_summary(valid.global_nearest_distance_m),"constrained_distance_m":numeric_summary(valid.context_nearest_distance_m),"distance_delta_m":numeric_summary(valid.context_minus_global_distance_m),"candidate_size_bins":candidate_size_bins(valid.context_candidate_count)},
            "contained_blank_road_id": {"count":len(blank),"same_nearest":int((blank.global_context_same_nearest==True).sum()),"different_nearest":int((blank.global_context_same_nearest==False).sum()),"empty_candidate_set":int((blank.context_candidate_count==0).sum()),"global_distance_m":numeric_summary(blank.global_nearest_distance_m),"constrained_distance_m":numeric_summary(blank.context_nearest_distance_m),"candidate_size_bins":candidate_size_bins(blank.context_candidate_count)},
            "outside_reference_coverage": {"count":len(outside),"global_distance_m":numeric_summary(outside.global_nearest_distance_m)},
            "coordinate_unavailable": int((result.road_context_status=="coordinate_unavailable").sum()),
        },
        "indexed_search_validation": brute,
        "outputs": {"neutral_path":neutral_output.relative_to(root).as_posix(),"neutral_rows":len(neutral),"neutral_fingerprint_sha256":neutral_fingerprint(neutral),"neutral_sha256":sha256_file(neutral_output),"validation_path":output.relative_to(root).as_posix(),"validation_rows":len(result),"validation_sha256":sha256_file(output),"validation_fingerprint_sha256":output_fingerprint(result),"qa_path":qa_path.relative_to(root).as_posix(),"qa_rows":len(qa),"qa_sha256":sha256_file(qa_path)},
        "semantics": {"formal_segment_assignment_performed":False,"formal_distance_threshold_selected":False,"flow_used_for_candidate_ranking":False,"epdo_calculated":False,"cbi_calculated":False,"risk_analysis_started":False},
        "readiness": {"phase8_4b":"READY_FOR_ANALYST_MATCHING_POLICY_DECISION_ONLY"},
    }
    receipt["receipt_fingerprint_sha256"]=stable_receipt_fingerprint(receipt); atomic_json(receipt_path,receipt); return receipt


def main():
    p=argparse.ArgumentParser(); root=Path(__file__).resolve().parents[1]; p.add_argument("--root",type=Path,default=root); p.add_argument("--output",type=Path); p.add_argument("--neutral-output",type=Path); p.add_argument("--qa",type=Path); p.add_argument("--receipt",type=Path); a=p.parse_args(); root=a.root.resolve()
    receipt=execute(root,(a.output or root/OUTPUT_PATH).resolve(),(a.neutral_output or root/NEUTRAL_PATH).resolve(),(a.qa or root/"notes/phase8_4a-candidate-qa-sample.csv").resolve(),(a.receipt or root/"notes/phase8_4a-accident-brouter-candidate-validation.json").resolve())
    print(json.dumps({"accidents":receipt["population"]["accidents"],"neutral_segments":receipt["neutral_segments"]["neutral_physical_segment_count"],"readiness":receipt["readiness"]["phase8_4b"]},ensure_ascii=False))

if __name__ == "__main__": main()
