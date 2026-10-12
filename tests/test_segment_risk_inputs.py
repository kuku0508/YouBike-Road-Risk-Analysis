import unittest
import numpy as np
import pandas as pd
from src.build_segment_risk_inputs import classify_severity, safe_rate, build_segment_table, frame_fingerprint, FATAL_WEIGHT, INJURY_WEIGHT

def exposure(rows=None):
 return pd.DataFrame(rows or [{"physical_segment_id":"1,1|2,2","endpoint1_lon_e6":1,"endpoint1_lat_e6":1,"endpoint2_lon_e6":2,"endpoint2_lat_e6":2,"directional_member_count":1,"bidirectional_total_trip_weight":100,"bidirectional_weekday_trip_weight":60,"bidirectional_holiday_trip_weight":40},{"physical_segment_id":"3,3|4,4","endpoint1_lon_e6":3,"endpoint1_lat_e6":3,"endpoint2_lon_e6":4,"endpoint2_lat_e6":4,"directional_member_count":2,"bidirectional_total_trip_weight":200,"bidirectional_weekday_trip_weight":0,"bidirectional_holiday_trip_weight":200}])
def eligible(rows=None):
 return pd.DataFrame(rows or [{"assigned_physical_segment_id":"1,1|2,2","severity_class":"fatal","day_type":"weekday"},{"assigned_physical_segment_id":"1,1|2,2","severity_class":"injury","day_type":"holiday"}])

class TestRiskInputs(unittest.TestCase):
 def test_01_immediate_death_fatal(self): self.assertEqual(classify_severity(1,0,0)[0],"classified_fatal")
 def test_02_30day_death_fatal(self): self.assertEqual(classify_severity(0,1,0)[0],"classified_fatal")
 def test_03_death_injury_once(self): self.assertEqual(classify_severity(1,0,3)[1],193)
 def test_04_injury(self): self.assertEqual(classify_severity(0,0,1)[0],"classified_injury")
 def test_05_missing(self): self.assertEqual(classify_severity(None,None,None,True)[0],"severity_unavailable")
 def test_06_negative_inconsistent(self): self.assertEqual(classify_severity(-1,0,1)[0],"inconsistent_source_fields")
 def test_07_fraction_inconsistent(self): self.assertEqual(classify_severity(0,0,1.5)[0],"inconsistent_source_fields")
 def test_08_zero_all_unavailable(self): self.assertEqual(classify_severity(0,0,0)[0],"severity_unavailable")
 def test_09_fatal_weight(self): self.assertEqual(FATAL_WEIGHT,193)
 def test_10_injury_weight(self): self.assertEqual(INJURY_WEIGHT,117)
 def test_11_fatal_injury_epdo(self): self.assertEqual(int(build_segment_table(exposure(),eligible())[0].iloc[0].epdo),310)
 def test_12_zero_segment_preserved(self): self.assertEqual(len(build_segment_table(exposure(),eligible())[0]),2)
 def test_13_accident_count(self): self.assertEqual(int(build_segment_table(exposure(),eligible())[0].accident_count.sum()),2)
 def test_14_fatal_count(self): self.assertEqual(int(build_segment_table(exposure(),eligible())[0].fatal_accident_count.sum()),1)
 def test_15_injury_count(self): self.assertEqual(int(build_segment_table(exposure(),eligible())[0].injury_accident_count.sum()),1)
 def test_16_weekday_holiday_count(self):
  o,*_=build_segment_table(exposure(),eligible()); self.assertEqual(int((o.weekday_accident_count+o.holiday_accident_count).sum()),2)
 def test_17_day_epdo_sum(self):
  o,*_=build_segment_table(exposure(),eligible()); self.assertTrue((o.weekday_epdo+o.holiday_epdo==o.epdo).all())
 def test_18_sri_max(self): self.assertEqual(build_segment_table(exposure(),eligible())[0].sri.max(),1)
 def test_19_ssi_max(self): self.assertEqual(build_segment_table(exposure(),eligible())[0].ssi.max(),1)
 def test_20_cbi_sum(self):
  o,*_=build_segment_table(exposure(),eligible()); self.assertTrue(np.allclose(o.cbi,o.sri+o.ssi))
 def test_21_zero_segment_cbi(self): self.assertEqual(build_segment_table(exposure(),eligible())[0].iloc[1].cbi,0)
 def test_22_total_rate(self): self.assertEqual(safe_rate([193],[100])[0],1930)
 def test_23_weekday_rate_uses_weekday(self): self.assertEqual(safe_rate([193],[50])[0],3860)
 def test_24_holiday_rate_uses_holiday(self): self.assertEqual(safe_rate([117],[30])[0],3900)
 def test_25_zero_weekday_null(self): self.assertTrue(np.isnan(safe_rate([0],[0])[0]))
 def test_26_zero_holiday_null(self): self.assertTrue(np.isnan(safe_rate([117],[0])[0]))
 def test_27_no_epsilon(self): self.assertTrue(np.isnan(safe_rate([1],[0])[0]))
 def test_28_median_full_universe(self): self.assertEqual(build_segment_table(exposure(),eligible())[1],30)
 def test_29_median_inclusive(self):
  o,w,_=build_segment_table(exposure(),eligible()); self.assertTrue((o.loc[o.weekday_trip_weight==w,"weekday_high_flow"]).all())
 def test_30_row_order_fingerprint(self):
  o,*_=build_segment_table(exposure(),eligible()); self.assertEqual(frame_fingerprint(o),frame_fingerprint(o.iloc[::-1]))
 def test_31_pdo_unobserved(self): self.assertTrue((build_segment_table(exposure(),eligible())[0].epdo_pdo_component_status=="unobserved").all())
 def test_32_population_label(self): self.assertTrue((build_segment_table(exposure(),eligible())[0].accident_population=="fatal_and_injury_accidents_only").all())
 def test_33_no_ranking_column(self): self.assertFalse(any("rank" in c or "hotspot" in c for c in build_segment_table(exposure(),eligible())[0].columns))

if __name__=="__main__":unittest.main()
