"""Deterministic route/segment primitives for road-routing-contract-v1."""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP

PRECISION = 6
FAILURE_STATUSES = {
    "success", "self_loop_not_routed", "missing_coordinate",
    "coordinate_conflict", "no_route", "brouter_error",
    "malformed_output", "snap_anomaly", "timeout",
}


def canonical_number(value: float, precision: int = PRECISION) -> str:
    if not math.isfinite(float(value)):
        raise ValueError("coordinate must be finite")
    quantum = Decimal(1).scaleb(-precision)
    return format(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP), f".{precision}f")


def canonical_point(point, precision: int = PRECISION) -> tuple[str, str]:
    if len(point) < 2:
        raise ValueError("point requires longitude and latitude")
    return canonical_number(point[0], precision), canonical_number(point[1], precision)


def directed_segment_key(start, end, precision: int = PRECISION) -> str:
    a, b = canonical_point(start, precision), canonical_point(end, precision)
    if a == b:
        raise ValueError("zero-length canonical segment")
    return f"{a[0]},{a[1]}->{b[0]},{b[1]}"


def extract_directed_segments(coordinates, precision: int = PRECISION) -> list[str]:
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        raise ValueError("route requires at least two coordinates")
    return [directed_segment_key(a, b, precision) for a, b in zip(coordinates, coordinates[1:])]


def parse_geojson_route(payload: dict, precision: int = PRECISION) -> dict:
    if payload.get("type") != "FeatureCollection":
        raise ValueError("expected GeoJSON FeatureCollection")
    line_features = [item for item in payload.get("features", [])
                     if item.get("geometry", {}).get("type") == "LineString"]
    if len(line_features) != 1:
        raise ValueError("expected exactly one LineString route")
    feature = line_features[0]
    geometry = feature.get("geometry", {})
    if geometry.get("type") != "LineString":
        raise ValueError("expected LineString route")
    coordinates = geometry.get("coordinates")
    segments = extract_directed_segments(coordinates, precision)
    canonical = json.dumps([[*canonical_point(p, precision)] for p in coordinates],
                           ensure_ascii=False, separators=(",", ":"))
    properties = feature.get("properties") or {}
    return {
        "coordinates": coordinates,
        "segments": segments,
        "segment_count": len(segments),
        "route_hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "properties": properties,
    }


def assign_trip_flow(segments: list[str], trip_count: int) -> Counter:
    if int(trip_count) <= 0:
        raise ValueError("trip_count must be positive")
    # Traversal-based: repeated traversal receives the full weight each time.
    return Counter({key: count * int(trip_count) for key, count in Counter(segments).items()})


def route_cache_key(*, origin_id, destination_id, origin_coordinate,
                    destination_coordinate, brouter_version, graph_hashes,
                    profile_hash, contract_version, coordinate_artifact_hash=None,
                    routing_parameters=None, precision=PRECISION) -> str:
    payload = {
        "origin_station_id": str(origin_id),
        "destination_station_id": str(destination_id),
        "origin_coordinate": canonical_point(origin_coordinate, precision),
        "destination_coordinate": canonical_point(destination_coordinate, precision),
        "brouter_version": brouter_version,
        "routing_graph_hashes": sorted(graph_hashes),
        "profile_hash": profile_hash,
        "contract_version": contract_version,
        "coordinate_artifact_hash": coordinate_artifact_hash,
        "routing_parameters": routing_parameters or {},
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def validate_cache_record(record: dict, expected_key: str, expected_output_hash: str) -> None:
    if record.get("cache_key") != expected_key:
        raise ValueError("stale cache identity")
    if record.get("output_sha256") != expected_output_hash:
        raise ValueError("cache output hash mismatch")


def classify_route(origin_id: str, destination_id: str, coordinates) -> str:
    if str(origin_id) == str(destination_id):
        return "self_loop_not_routed"
    if coordinates is None:
        return "missing_coordinate"
    return "success"
