import copy
import unittest

from src.route_segment_utils import (FAILURE_STATUSES, assign_trip_flow,
    canonical_point, classify_route, directed_segment_key,
    extract_directed_segments, parse_geojson_route, route_cache_key,
    validate_cache_record)


ROUTE = {"type":"FeatureCollection","features":[{"type":"Feature",
    "properties":{"track-length":123},"geometry":{"type":"LineString",
    "coordinates":[[121.5000004,25.0000004],[121.51,25.01],[121.5,25.0]]}}]}


class RouteSegmentUtilsTests(unittest.TestCase):
    def test_coordinate_canonicalization(self):
        self.assertEqual(canonical_point((121.5000004,25.0000004)), ("121.500000","25.000000"))
    def test_directed_segment_identity(self):
        a=directed_segment_key((1,2),(3,4)); b=directed_segment_key((3,4),(1,2)); self.assertNotEqual(a,b)
    def test_zero_length_fails(self):
        with self.assertRaises(ValueError): directed_segment_key((1,2),(1,2))
    def test_route_parser(self):
        parsed=parse_geojson_route(ROUTE); self.assertEqual(parsed["segment_count"],2); self.assertEqual(len(parsed["route_hash"]),64)
    def test_malformed_route_fails_closed(self):
        bad=copy.deepcopy(ROUTE); bad["features"][0]["geometry"]["type"]="Point"
        with self.assertRaises(ValueError): parse_geojson_route(bad)
    def test_reciprocal_routes_preserved(self):
        forward=extract_directed_segments([[1,2],[3,4]]); reverse=extract_directed_segments([[3,4],[1,2]]); self.assertNotEqual(forward,reverse)
    def test_weight_assignment(self):
        self.assertEqual(assign_trip_flow(["a","b"],7), {"a":7,"b":7})
    def test_repeated_segment_is_traversal_based(self):
        self.assertEqual(assign_trip_flow(["a","a"],7)["a"],14)
    def test_self_loop_policy(self):
        self.assertEqual(classify_route("A","A",[(1,2),(3,4)]),"self_loop_not_routed")
    def test_missing_coordinate_fails_closed(self):
        self.assertEqual(classify_route("A","B",None),"missing_coordinate")
    def test_failure_taxonomy(self):
        self.assertEqual(len(FAILURE_STATUSES),9); self.assertIn("timeout",FAILURE_STATUSES)
    def test_cache_key_deterministic(self):
        kw=dict(origin_id="A",destination_id="B",origin_coordinate=(1,2),destination_coordinate=(3,4),brouter_version="1",graph_hashes=["g2","g1"],profile_hash="p",contract_version="v1")
        self.assertEqual(route_cache_key(**kw),route_cache_key(**kw))
    def test_cache_key_covers_direction(self):
        base=dict(origin_coordinate=(1,2),destination_coordinate=(3,4),brouter_version="1",graph_hashes=["g"],profile_hash="p",contract_version="v1")
        self.assertNotEqual(route_cache_key(origin_id="A",destination_id="B",**base),route_cache_key(origin_id="B",destination_id="A",**base))
    def test_stale_cache_rejected(self):
        with self.assertRaises(ValueError): validate_cache_record({"cache_key":"old","output_sha256":"h"},"new","h")
    def test_output_hash_gate(self):
        with self.assertRaises(ValueError): validate_cache_record({"cache_key":"k","output_sha256":"old"},"k","new")


if __name__ == "__main__": unittest.main()
