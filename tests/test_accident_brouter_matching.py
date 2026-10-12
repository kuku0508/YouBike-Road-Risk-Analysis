import unittest
import pandas as pd
from src.match_accidents_to_brouter_segments import build_exposure, classify, match, matching_fingerprint, sensitivity, SpatialContractError
from src.validate_accident_brouter_candidates import DIRECTED_COLUMNS, OUTPUT_COLUMNS

def candidate(status="contained_valid_road",cd=1.0,gd=.5,cc=1,ct=1,gt=1,gap=.2):
 d={c:None for c in OUTPUT_COLUMNS}; d.update(reconstructed_accident_id="a",road_context_status=status,context_candidate_count=cc,context_nearest_segment_key="1,1|2,2",context_nearest_distance_m=cd,context_second_distance_m=cd+gap,context_distance_gap_m=gap,context_exact_tie_count=ct,global_nearest_segment_key="3,3|4,4",global_nearest_distance_m=gd,global_second_distance_m=gd+gap,global_distance_gap_m=gap,global_exact_tie_count=gt); return pd.Series(d)
def directed(rows): return pd.DataFrame(rows,columns=DIRECTED_COLUMNS)

class TestMatching(unittest.TestCase):
 def test_01_context_match(self): self.assertEqual(classify(candidate())[0],"matched_context")
 def test_02_context_beats_closer_global(self): self.assertEqual(classify(candidate(cd=9,gd=0))[2],"1,1|2,2")
 def test_03_context_empty(self): self.assertEqual(classify(candidate(cc=0))[0],"context_no_brouter_candidate")
 def test_04_no_global_fallback(self): self.assertIsNone(classify(candidate(cc=0))[2])
 def test_05_outside_global_match(self): self.assertEqual(classify(candidate(status="outside_reference_coverage"))[0],"matched_global")
 def test_06_outside_far(self): self.assertEqual(classify(candidate(status="outside_reference_coverage",gd=11))[0],"unmatched_distance")
 def test_07_exactly_ten(self): self.assertEqual(classify(candidate(cd=10))[0],"matched_context")
 def test_08_over_ten(self): self.assertEqual(classify(candidate(cd=10.0001))[0],"unmatched_distance")
 def test_09_tie_near(self): self.assertEqual(classify(candidate(ct=2))[0],"ambiguous_exact_tie")
 def test_10_tie_far_distance_wins(self): self.assertEqual(classify(candidate(cd=11,ct=2))[0],"unmatched_distance")
 def test_11_near_tie_unique_matches(self): self.assertEqual(classify(candidate(gap=.0001))[0],"matched_context")
 def test_12_coordinate_unavailable(self): self.assertEqual(classify(candidate(status="coordinate_unavailable"))[0],"coordinate_unavailable")
 def test_13_blank_uses_context(self): self.assertEqual(classify(candidate(status="contained_blank_road_id"))[0],"matched_context")
 def test_14_blank_basis(self): self.assertEqual(classify(candidate(status="contained_blank_road_id"))[1],"road_context_constrained")
 def test_15_bidirectional_sum(self):
  e,t=build_exposure(directed([(1,1,2,2,1,1,10,7,3),(2,2,1,1,1,1,20,13,7)])); self.assertEqual(int(e.iloc[0].bidirectional_total_trip_weight),30)
 def test_16_one_direction(self): self.assertEqual(build_exposure(directed([(1,1,2,2,1,1,10,7,3)]))[0].iloc[0].directional_member_count,1)
 def test_17_day_sum(self):
  e,_=build_exposure(directed([(1,1,2,2,1,1,10,7,3)])); self.assertEqual(e.iloc[0].bidirectional_total_trip_weight,e.iloc[0].bidirectional_weekday_trip_weight+e.iloc[0].bidirectional_holiday_trip_weight)
 def test_18_conservation(self): self.assertEqual(build_exposure(directed([(1,1,2,2,1,1,10,7,3)]))[1],(10,7,3))
 def test_19_contained_multiple(self): self.assertEqual(classify(candidate(status="contained_multiple"))[0],"contained_multiple_unresolved")
 def test_20_sensitivity_primary_independent(self):
  c=pd.DataFrame([candidate(cd=7)]); self.assertEqual(sensitivity(c)["5m"]["unmatched_distance"],1); self.assertEqual(sensitivity(c)["10m"]["matched_context"],1)
 def test_21_flow_not_in_candidate(self): self.assertFalse(any("weight" in x for x in OUTPUT_COLUMNS))
 def test_22_negative_exposure_fails(self):
  with self.assertRaises(SpatialContractError): build_exposure(directed([(1,1,2,2,1,1,-1,0,-1)]))
 def test_23_bad_day_sum_fails(self):
  with self.assertRaises(SpatialContractError): build_exposure(directed([(1,1,2,2,1,1,10,6,3)]))
 def test_24_fingerprint_order_independent(self):
  row={c:None for c in __import__('src.match_accidents_to_brouter_segments',fromlist=['MATCH_COLUMNS']).MATCH_COLUMNS}; row.update(reconstructed_accident_id="b",year=2023,event_datetime="x",road_context_status="coordinate_unavailable",match_status="coordinate_unavailable",match_basis="none",road_context_constrained=False,source_accident_context_fingerprint="a",source_candidate_validation_fingerprint="b",source_direction_neutral_fingerprint="c"); f=pd.DataFrame([row,{**row,"reconstructed_accident_id":"a"}]); self.assertEqual(matching_fingerprint(f),matching_fingerprint(f.iloc[::-1]))
 def test_25_invalid_context_fails(self):
  with self.assertRaises(SpatialContractError): classify(candidate(status="new"))
 def test_26_primary_threshold_positive(self):
  a=pd.DataFrame([{"reconstructed_accident_id":"a","year":2023,"event_datetime":"x","road_context_status":"contained_valid_road"}]); c=pd.DataFrame([candidate()]); e,_=build_exposure(directed([(1,1,2,2,1,1,10,7,3)]))
  with self.assertRaises(SpatialContractError): match(a,c,e,0)

if __name__=="__main__": unittest.main()
