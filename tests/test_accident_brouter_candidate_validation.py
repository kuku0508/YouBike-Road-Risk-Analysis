import math
import unittest

import pandas as pd
from shapely.geometry import LineString, Point, Polygon
from shapely.strtree import STRtree

from src.validate_accident_brouter_candidates import (
    SpatialContractError, build_neutral_segments, candidate_profile,
    candidate_size_bins, gap_bin, global_profile, neutral_key,
    output_fingerprint, segment_key,
    categorical_counts,
)


COLS=["from_lon_e6","from_lat_e6","to_lon_e6","to_lat_e6","segment_traversal_count","unique_route_count","total_trip_weight","weekday_trip_weight","holiday_trip_weight"]
def directed(rows): return pd.DataFrame([(*r,1,1,1,1,0) for r in rows],columns=COLS)


class TestAccidentBrouterCandidateValidation(unittest.TestCase):
    def test_01_neutral_key_lexicographic(self): self.assertEqual(neutral_key(next(directed([(2,2,1,1)]).itertuples())),(1,1,2,2))
    def test_02_zero_length_fails(self):
        with self.assertRaises(SpatialContractError): neutral_key(next(directed([(1,1,1,1)]).itertuples()))
    def test_03_reciprocal_collapses(self): self.assertEqual(len(build_neutral_segments(directed([(1,1,2,2),(2,2,1,1)]))[0]),1)
    def test_04_one_direction_count(self): self.assertEqual(build_neutral_segments(directed([(1,1,2,2)]))[1]["one_direction_only_count"],1)
    def test_05_both_directions_count(self): self.assertEqual(build_neutral_segments(directed([(1,1,2,2),(2,2,1,1)]))[1]["both_directions_count"],1)
    def test_06_duplicate_same_direction_fails(self):
        with self.assertRaises(SpatialContractError): build_neutral_segments(directed([(1,1,2,2),(1,1,2,2)]))
    def test_07_gt2_fails(self):
        with self.assertRaises(SpatialContractError): build_neutral_segments(directed([(1,1,2,2),(2,2,1,1),(1,1,2,2)]))
    def test_08_member_conservation(self): self.assertTrue(build_neutral_segments(directed([(1,1,2,2),(2,2,1,1)]))[1]["directed_member_conservation"])
    def test_09_segment_key_integer_identity(self): self.assertEqual(segment_key((1,2,3,4)),"1,2|3,4")
    def test_10_profile_nearest(self):
        g=[LineString([(0,0),(0,2)]),LineString([(5,0),(5,2)])]; p=candidate_profile(Point(1,1),g,["a","b"],[0,1]); self.assertEqual(p["key"],"a")
    def test_11_profile_second(self):
        g=[LineString([(0,0),(0,2)]),LineString([(5,0),(5,2)])]; self.assertEqual(candidate_profile(Point(1,1),g,["a","b"],[0,1])["second"],4)
    def test_12_exact_tie_count(self):
        g=[LineString([(0,0),(0,2)]),LineString([(2,0),(2,2)])]; self.assertEqual(candidate_profile(Point(1,1),g,["a","b"],[0,1])["ties"],2)
    def test_13_tie_order_is_key_order(self):
        g=[LineString([(0,0),(0,2)]),LineString([(2,0),(2,2)])]; self.assertEqual(candidate_profile(Point(1,1),g,["z","a"],[0,1])["key"],"a")
    def test_14_empty_context(self): self.assertIsNone(candidate_profile(Point(0,0),[],[],[])["key"])
    def test_15_single_context_has_no_second(self): self.assertIsNone(candidate_profile(Point(0,0),[LineString([(1,0),(1,1)])],["a"],[0])["second"])
    def test_16_gap_bins(self): self.assertEqual(gap_bin(.1),"<= 0.1 m")
    def test_17_gap_bin_large(self): self.assertEqual(gap_bin(5.1),"> 5 m")
    def test_18_global_index_matches_brute(self):
        g=[LineString([(0,0),(0,2)]),LineString([(5,0),(5,2)]),LineString([(9,0),(9,2)])]; keys=["a","b","c"]; p=Point(1,1); self.assertEqual(global_profile(p,STRtree(g),g,keys),candidate_profile(p,g,keys,[0,1,2]))
    def test_19_intersects_includes_crossing(self): self.assertTrue(LineString([(-1,1),(3,1)]).intersects(Polygon([(0,0),(2,0),(2,2),(0,2)])))
    def test_20_intersects_includes_touch(self): self.assertTrue(LineString([(-1,0),(0,0)]).intersects(Polygon([(0,0),(2,0),(2,2),(0,2)])))
    def test_21_midpoint_outside_can_intersect(self):
        line=LineString([(-10,1),(1,1)]); poly=Polygon([(0,0),(2,0),(2,2),(0,2)]); self.assertFalse(poly.covers(line.interpolate(.5,normalized=True))); self.assertTrue(line.intersects(poly))
    def test_22_candidate_bins(self): self.assertEqual(candidate_size_bins(pd.Series([0,1,2,3,6,11,21])),{"0":1,"1":1,"2":1,"3-5":1,"6-10":1,"11-20":1,">20":1})
    def test_23_fingerprint_order_independent(self):
        cols=__import__('src.validate_accident_brouter_candidates',fromlist=['OUTPUT_COLUMNS']).OUTPUT_COLUMNS; row={c:None for c in cols}; row.update(reconstructed_accident_id="b",road_context_status="outside_reference_coverage",global_nearest_distance_m=1.0); f=pd.DataFrame([row,{**row,"reconstructed_accident_id":"a"}],columns=cols); self.assertEqual(output_fingerprint(f),output_fingerprint(f.iloc[::-1]))
    def test_24_flow_not_in_neutral_artifact(self):
        frame,_=build_neutral_segments(directed([(1,1,2,2)])); self.assertFalse(any("trip_weight" in c for c in frame.columns))
    def test_25_reverse_direction_metadata_preserved(self):
        frame,_=build_neutral_segments(directed([(1,1,2,2),(2,2,1,1)])); self.assertTrue(frame.iloc[0].has_forward_member and frame.iloc[0].has_reverse_member)
    def test_26_no_assignment_field(self):
        cols=__import__('src.validate_accident_brouter_candidates',fromlist=['OUTPUT_COLUMNS']).OUTPUT_COLUMNS; self.assertNotIn("assigned_segment_id",cols)
    def test_27_categorical_counts_are_json_safe(self):
        self.assertEqual(categorical_counts(pd.Series(["a", None, float("nan")])), {"a": 1, "null": 2})
    def test_28_second_key_is_distinct_physical_segment(self):
        g=[LineString([(0,0),(0,2)]),LineString([(5,0),(5,2)])]; p=candidate_profile(Point(1,1),g,["a","b"],[0,1]); self.assertEqual(p["second_key"],"b")

if __name__ == "__main__": unittest.main()
