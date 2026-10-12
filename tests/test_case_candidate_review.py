import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from src.build_case_candidate_review import (
    PRIMARY_CLASSES,
    REVIEW_EXPLANATION,
    build_review_tables,
    render_review_map,
    review_fingerprint,
    validate_locked_inputs,
)
from src.validate_accident_road_reference import SpatialContractError, sha256_file


def canonical_frame():
    classes = ["q90_q95", "above_q95", "q90_q95", "q75_q90", "positive_le_q50", "zero"]
    cbi = [0.25, 0.5, 0.25, 0.15, 0.05, 0.0]
    return pd.DataFrame({
        "physical_segment_id": [f"s{i}" for i in range(6)],
        "endpoint1_lon_e6": 121500000 + np.arange(6)*100,
        "endpoint1_lat_e6": 25000000 + np.arange(6)*100,
        "endpoint2_lon_e6": 121500100 + np.arange(6)*100,
        "endpoint2_lat_e6": 25000100 + np.arange(6)*100,
        "cbi": cbi, "sri": np.array(cbi)/3, "ssi": np.array(cbi)*2/3,
        "fatal_accident_count": [0,1,0,0,0,0], "injury_accident_count": [2,2,1,1,1,0],
        "accident_count": [2,3,1,1,1,0], "epdo": [234,427,117,117,117,0],
        "weekday_high_flow": [True,True,False,True,True,False],
        "holiday_high_flow": [False,True,True,False,False,False],
        "weekday_trip_weight": [5000,6000,100,7000,8000,50], "holiday_trip_weight": [100,3000,4000,100,200,50],
        "weekday_epdo_per_1000_trips": [46.8,71.1666667,1170,16.7142857,14.625,0],
        "holiday_epdo_per_1000_trips": [2340,142.3333333,29.25,1170,585,0],
    }), classes


def presentation_frame():
    canonical, classes = canonical_frame(); rows=[]
    for i,row in canonical.iterrows():
        for day,flag in [("weekday",row.weekday_high_flow),("holiday",row.holiday_high_flow)]:
            if flag:
                rows.append({"day_type":day,"physical_segment_id":row.physical_segment_id,"cbi":row.cbi,"cbi_display_class":classes[i],"segment_length_m":10+i,"endpoint1_lon_e6":row.endpoint1_lon_e6,"endpoint1_lat_e6":row.endpoint1_lat_e6,"endpoint2_lon_e6":row.endpoint2_lon_e6,"endpoint2_lat_e6":row.endpoint2_lat_e6})
    return pd.DataFrame(rows), canonical


class TestCaseCandidateReview(unittest.TestCase):
    def setUp(self):
        self.presentation,self.canonical=presentation_frame(); self.worksheet,self.secondary=build_review_tables(self.presentation,self.canonical)

    def test_01_primary_is_high_flow_in_at_least_one_day(self): self.assertTrue((self.worksheet.weekday_candidate_review|self.worksheet.holiday_candidate_review).all())
    def test_02_q90_q95_included(self): self.assertEqual(set(self.worksheet[self.worksheet.cbi_display_class=="q90_q95"].physical_segment_id),{"s0","s2"})
    def test_03_above_q95_included(self): self.assertEqual(set(self.worksheet[self.worksheet.cbi_display_class=="above_q95"].physical_segment_id),{"s1"})
    def test_04_q75_q90_excluded_from_primary(self): self.assertNotIn("s3",set(self.worksheet.physical_segment_id))
    def test_05_lower_classes_excluded(self): self.assertTrue(set(self.worksheet.cbi_display_class).issubset(PRIMARY_CLASSES))
    def test_06_canonical_cbi_unchanged(self):
        joined=self.worksheet.merge(self.canonical[["physical_segment_id","cbi"]],on="physical_segment_id",suffixes=("","_canonical")); np.testing.assert_array_equal(joined.cbi,joined.cbi_canonical)
    def test_07_unique_physical_segment(self): self.assertTrue(self.worksheet.physical_segment_id.is_unique)
    def test_08_daytype_candidate_flags(self):
        row=self.worksheet.set_index("physical_segment_id").loc["s0"]; self.assertTrue(row.weekday_candidate_review); self.assertFalse(row.holiday_candidate_review)
    def test_09_both_daytype_state(self): self.assertEqual(self.worksheet.set_index("physical_segment_id").loc["s1","candidate_daytype_state"],"both_daytypes_candidate")
    def test_10_no_ranking_column(self): self.assertFalse(any("rank" in c.lower() for c in self.worksheet.columns))
    def test_11_no_hotspot_flag(self): self.assertFalse(any("hotspot" in c.lower() for c in self.worksheet.columns))
    def test_12_blank_review_status(self): self.assertTrue((self.worksheet.review_status=="").all())
    def test_13_blank_researcher_note(self): self.assertTrue((self.worksheet.researcher_note=="").all())
    def test_14_row_reorder_fingerprint(self): self.assertEqual(review_fingerprint(self.worksheet),review_fingerprint(self.worksheet.sample(frac=1,random_state=5)))
    def test_15_upstream_mismatch_fails_closed(self):
        with self.assertRaisesRegex(SpatialContractError,"receipt mismatch"): validate_locked_inputs({},self.presentation,self.canonical,"bad","bad")
    def test_16_secondary_context_separate(self): self.assertEqual(set(self.secondary.physical_segment_id),{"s3"})
    def test_17_review_map_deterministic(self):
        with tempfile.TemporaryDirectory() as d:
            a=Path(d)/"a.png"; b=Path(d)/"b.png"; render_review_map(self.presentation,self.worksheet,self.secondary,a); render_review_map(self.presentation,self.worksheet,self.secondary,b); self.assertEqual(sha256_file(a),sha256_file(b))

    def test_18_traditional_chinese_explanation_is_locked(self):
        self.assertEqual(REVIEW_EXPLANATION, "視覺化級距僅用於縮小人工檢視範圍，不代表熱點定義或危險程度排名。")


if __name__=="__main__": unittest.main()
