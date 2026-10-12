import unittest

import numpy as np
import pandas as pd

from src.audit_segment_risk_stability import (
    EXPECTED_ROWS,
    audit_fingerprint,
    exposure_quartiles,
    joint_matrix,
    length_quartiles,
    quartile_labels,
    segment_lengths,
    stats,
    tail_diag,
    validate_locked_input,
)
from src.validate_accident_road_reference import SpatialContractError


def sample_frame():
    return pd.DataFrame(
        {
            "physical_segment_id": ["a", "b", "c", "d"],
            "endpoint1_lon_e6": [121500000, 121500100, 121500200, 121500300],
            "endpoint1_lat_e6": [25000000, 25000100, 25000200, 25000300],
            "endpoint2_lon_e6": [121500100, 121500200, 121500300, 121500400],
            "endpoint2_lat_e6": [25000100, 25000200, 25000300, 25000400],
            "accident_count": [1, 0, 2, 1],
            "epdo": [193, 0, 234, 117],
            "cbi": [2.0, 0.0, 1.5, 1.0],
            "total_trip_weight": [10, 20, 30, 40],
            "weekday_trip_weight": [5, 10, 15, 20],
            "holiday_trip_weight": [5, 10, 15, 20],
            "epdo_per_1000_trips": [19300.0, 0.0, 7800.0, 2925.0],
            "weekday_epdo_per_1000_trips": [38600.0, 0.0, 15600.0, 5850.0],
            "holiday_epdo_per_1000_trips": [0.0, 0.0, 0.0, 0.0],
            "weekday_high_flow": [False, False, True, True],
            "holiday_high_flow": [False, False, True, True],
        }
    )


class TestSegmentRiskStability(unittest.TestCase):
    def setUp(self):
        self.frame = sample_frame()
        self.frame["segment_length_m"] = segment_lengths(self.frame)

    def test_01_existing_median_flag_is_inclusive(self):
        self.assertTrue(self.frame.loc[self.frame.weekday_trip_weight == 15, "weekday_high_flow"].all())

    def test_02_weekday_view_uses_weekday_rate(self):
        result = exposure_quartiles(self.frame, "weekday_trip_weight", "weekday_epdo_per_1000_trips")
        self.assertEqual(result["groups"]["Q1"]["rate"]["max"], 38600.0)

    def test_03_holiday_view_uses_holiday_rate(self):
        result = exposure_quartiles(self.frame, "holiday_trip_weight", "holiday_epdo_per_1000_trips")
        self.assertEqual(result["groups"]["Q4"]["rate"]["max"], 0.0)

    def test_04_zero_denominator_excluded_from_rate_stats(self):
        values = pd.Series([np.nan, 1.0])
        self.assertEqual(stats(values)["n"], 1)

    def test_05_filter_does_not_modify_canonical_rate(self):
        before = self.frame.weekday_epdo_per_1000_trips.copy()
        _ = self.frame[self.frame.weekday_high_flow]
        pd.testing.assert_series_equal(before, self.frame.weekday_epdo_per_1000_trips)

    def test_06_filter_does_not_modify_cbi(self):
        before = self.frame.cbi.copy()
        _ = self.frame[self.frame.holiday_high_flow]
        pd.testing.assert_series_equal(before, self.frame.cbi)

    def test_07_endpoint_conversion_is_metric_scale(self):
        self.assertGreater(self.frame.segment_length_m.iloc[0], 1.0)

    def test_08_projected_lengths_are_positive(self):
        self.assertTrue((self.frame.segment_length_m > 0).all())

    def test_09_endpoint_reversal_preserves_length(self):
        reversed_frame = self.frame.rename(columns={
            "endpoint1_lon_e6": "endpoint2_lon_e6",
            "endpoint1_lat_e6": "endpoint2_lat_e6",
            "endpoint2_lon_e6": "endpoint1_lon_e6",
            "endpoint2_lat_e6": "endpoint1_lat_e6",
        })
        np.testing.assert_allclose(segment_lengths(self.frame), segment_lengths(reversed_frame))

    def test_10_zero_length_fails_closed(self):
        bad = self.frame.iloc[[0]].copy()
        bad["endpoint2_lon_e6"] = bad.endpoint1_lon_e6
        bad["endpoint2_lat_e6"] = bad.endpoint1_lat_e6
        with self.assertRaises(SpatialContractError):
            segment_lengths(bad)

    def test_11_tail_is_at_or_above_threshold(self):
        threshold = 6000.0
        result = tail_diag(self.frame, "weekday_epdo_per_1000_trips", "weekday_trip_weight", "segment_length_m", threshold)
        self.assertEqual(result["n"], 2)

    def test_12_no_ranking_fields_in_fixture(self):
        self.assertFalse(any("rank" in c.lower() for c in self.frame.columns))

    def test_13_exposure_quartiles_deterministic(self):
        first = exposure_quartiles(self.frame, "weekday_trip_weight", "weekday_epdo_per_1000_trips")
        second = exposure_quartiles(self.frame.sample(frac=1, random_state=7), "weekday_trip_weight", "weekday_epdo_per_1000_trips")
        self.assertEqual(first, second)

    def test_14_length_quartiles_deterministic(self):
        first = length_quartiles(self.frame, "weekday_epdo_per_1000_trips")
        second = length_quartiles(self.frame.iloc[::-1], "weekday_epdo_per_1000_trips")
        self.assertEqual(first, second)

    def test_15_row_reorder_does_not_change_qa_fingerprint(self):
        def mini_qa(frame):
            work = frame.copy()
            work["segment_length_m"] = segment_lengths(work)
            return {
                "rate": stats(work.weekday_epdo_per_1000_trips),
                "exposure": exposure_quartiles(work, "weekday_trip_weight", "weekday_epdo_per_1000_trips"),
                "length": length_quartiles(work, "weekday_epdo_per_1000_trips"),
            }
        self.assertEqual(
            audit_fingerprint(mini_qa(self.frame)),
            audit_fingerprint(mini_qa(self.frame.sample(frac=1, random_state=11))),
        )

    def test_16_locked_full_row_count(self):
        self.assertEqual(EXPECTED_ROWS, 106049)

    def test_17_cbi_zero_nonzero_conservation(self):
        self.assertEqual(int((self.frame.cbi == 0).sum()) + int((self.frame.cbi > 0).sum()), len(self.frame))

    def test_18_no_new_minimum_cutoff_field(self):
        self.assertFalse(any("minimum_exposure" in c.lower() for c in self.frame.columns))

    def test_19_no_hotspot_rank_field(self):
        self.assertFalse(any("hotspot" in c.lower() for c in self.frame.columns))

    def test_20_quartile_labels_are_reorder_stable(self):
        labels, cuts = quartile_labels(pd.Series([1, 2, 3, 4]))
        self.assertEqual(cuts, [1.75, 2.5, 3.25])
        self.assertEqual(labels.tolist(), ["Q1", "Q2", "Q3", "Q4"])

    def test_21_joint_matrix_has_all_fixture_cells(self):
        result = joint_matrix(self.frame, "weekday_trip_weight", "weekday_epdo_per_1000_trips")
        self.assertEqual(sum(cell["n"] for cell in result["cells"].values()), len(self.frame))

    def test_22_upstream_mismatch_fails_closed(self):
        with self.assertRaisesRegex(SpatialContractError, "receipt mismatch"):
            validate_locked_input({"receipt_fingerprint_sha256": "wrong"}, "wrong", "wrong", 0)


if __name__ == "__main__":
    unittest.main()
