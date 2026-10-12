import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from src.build_risk_presentation import (
    CBI_LABELS,
    RATE_LABELS,
    build_presentation,
    classify_display,
    counts_by_day,
    overlap_counts,
    presentation_fingerprint,
    quantiles,
    render_figures,
    validate_locked_inputs,
    validate_presentation,
    write_geoparquet,
)
from src.validate_accident_road_reference import SpatialContractError, sha256_file


def source_frame():
    n = 6
    total_fatal = np.array([0, 1, 0, 0, 1, 0])
    total_injury = np.array([0, 0, 1, 2, 1, 0])
    weekday_fatal = np.array([0, 1, 0, 0, 0, 0])
    weekday_injury = np.array([0, 0, 1, 0, 1, 0])
    holiday_fatal = total_fatal - weekday_fatal
    holiday_injury = total_injury - weekday_injury
    weekday_epdo = weekday_fatal * 193 + weekday_injury * 117
    holiday_epdo = holiday_fatal * 193 + holiday_injury * 117
    weekday_exposure = np.array([10, 20, 30, 40, 50, 60])
    holiday_exposure = np.array([15, 25, 35, 45, 55, 65])
    cbi = np.array([0.0, .1, .1, .2, .4, 1.0])
    return pd.DataFrame({
        "physical_segment_id": [f"s{i}" for i in range(n)],
        "endpoint1_lon_e6": 121500000 + np.arange(n) * 100,
        "endpoint1_lat_e6": 25000000 + np.arange(n) * 100,
        "endpoint2_lon_e6": 121500100 + np.arange(n) * 100,
        "endpoint2_lat_e6": 25000100 + np.arange(n) * 100,
        "directional_member_count": [1, 2, 1, 2, 1, 2],
        "fatal_accident_count": total_fatal,
        "injury_accident_count": total_injury,
        "accident_count": total_fatal + total_injury,
        "weekday_fatal_accident_count": weekday_fatal,
        "weekday_injury_accident_count": weekday_injury,
        "weekday_accident_count": weekday_fatal + weekday_injury,
        "holiday_fatal_accident_count": holiday_fatal,
        "holiday_injury_accident_count": holiday_injury,
        "holiday_accident_count": holiday_fatal + holiday_injury,
        "epdo": weekday_epdo + holiday_epdo,
        "weekday_epdo": weekday_epdo,
        "holiday_epdo": holiday_epdo,
        "weekday_trip_weight": weekday_exposure,
        "holiday_trip_weight": holiday_exposure,
        "weekday_epdo_per_1000_trips": weekday_epdo * 1000 / weekday_exposure,
        "holiday_epdo_per_1000_trips": holiday_epdo * 1000 / holiday_exposure,
        "weekday_high_flow": [True, True, True, False, False, False],
        "holiday_high_flow": [False, True, True, True, False, False],
        "cbi": cbi,
        "sri": cbi / 3,
        "ssi": cbi * 2 / 3,
    })


class TestRiskPresentation(unittest.TestCase):
    def setUp(self):
        self.source = source_frame()
        self.out, self.cbi_thresholds, self.rate_thresholds, self.pooled_positive_n = build_presentation(self.source)

    def test_01_weekday_only_high_flow(self):
        self.assertEqual(set(self.out.loc[self.out.day_type == "weekday", "physical_segment_id"]), {"s0", "s1", "s2"})

    def test_02_holiday_only_high_flow(self):
        self.assertEqual(set(self.out.loc[self.out.day_type == "holiday", "physical_segment_id"]), {"s1", "s2", "s3"})

    def test_03_cbi_unchanged(self):
        joined = self.out.merge(self.source[["physical_segment_id", "cbi"]], on="physical_segment_id", suffixes=("", "_source"))
        np.testing.assert_array_equal(joined.cbi, joined.cbi_source)

    def test_04_sri_unchanged(self):
        joined = self.out.merge(self.source[["physical_segment_id", "sri"]], on="physical_segment_id", suffixes=("", "_source"))
        np.testing.assert_array_equal(joined.sri, joined.sri_source)

    def test_05_ssi_unchanged(self):
        joined = self.out.merge(self.source[["physical_segment_id", "ssi"]], on="physical_segment_id", suffixes=("", "_source"))
        np.testing.assert_array_equal(joined.ssi, joined.ssi_source)

    def test_06_same_segment_same_cbi_across_day_types(self):
        pivot = self.out.pivot(index="physical_segment_id", columns="day_type", values="cbi").dropna()
        np.testing.assert_array_equal(pivot.weekday, pivot.holiday)

    def test_07_weekday_numerator_fields(self):
        row = self.out[(self.out.day_type == "weekday") & (self.out.physical_segment_id == "s1")].iloc[0]
        self.assertEqual(row.day_type_epdo, self.source.loc[1, "weekday_epdo"])

    def test_08_holiday_numerator_fields(self):
        row = self.out[(self.out.day_type == "holiday") & (self.out.physical_segment_id == "s3")].iloc[0]
        self.assertEqual(row.day_type_accident_count, self.source.loc[3, "holiday_accident_count"])

    def test_09_weekday_rate_uses_weekday_exposure(self):
        row = self.out[(self.out.day_type == "weekday") & (self.out.physical_segment_id == "s1")].iloc[0]
        self.assertEqual(row.day_type_epdo_per_1000_trips, self.source.loc[1, "weekday_epdo_per_1000_trips"])

    def test_10_holiday_rate_uses_holiday_exposure(self):
        row = self.out[(self.out.day_type == "holiday") & (self.out.physical_segment_id == "s3")].iloc[0]
        self.assertEqual(row.day_type_epdo_per_1000_trips, self.source.loc[3, "holiday_epdo_per_1000_trips"])

    def test_11_no_zero_denominator(self):
        self.assertTrue((self.out.day_type_estimated_exposure > 0).all())

    def test_12_cbi_zero_class(self):
        row = self.out[(self.out.day_type == "weekday") & (self.out.physical_segment_id == "s0")].iloc[0]
        self.assertEqual(row.cbi_display_class, "zero")

    def test_13_global_cbi_thresholds_shared(self):
        self.assertEqual(self.cbi_thresholds, quantiles(self.source.loc[self.source.cbi > 0, "cbi"], [.5, .75, .9, .95]))

    def test_14_tie_at_threshold_is_in_lower_class(self):
        result = classify_display(pd.Series([.1]), [.1, .2, .3, .4], CBI_LABELS)
        self.assertEqual(result.iloc[0], "positive_le_q50")

    def test_15_duplicate_thresholds_are_not_jittered(self):
        result = classify_display(pd.Series([.1, .15, .2, .3]), [.1, .1, .2, .2], CBI_LABELS)
        self.assertEqual(result.tolist(), ["positive_le_q50", "q75_q90", "q75_q90", "above_q95"])

    def test_16_pooled_rate_universe_contains_both_days(self):
        expected = pd.concat([self.source.loc[self.source.weekday_high_flow, "weekday_epdo_per_1000_trips"], self.source.loc[self.source.holiday_high_flow, "holiday_epdo_per_1000_trips"]])
        self.assertEqual(self.pooled_positive_n, int((expected > 0).sum()))

    def test_17_rate_thresholds_shared(self):
        for day in ["weekday", "holiday"]:
            expected = classify_display(self.out.loc[self.out.day_type == day, "day_type_epdo_per_1000_trips"], self.rate_thresholds, RATE_LABELS)
            self.assertEqual(expected.tolist(), self.out.loc[self.out.day_type == day, "rate_display_class"].tolist())

    def test_18_raw_rate_unchanged(self):
        self.assertEqual(self.out.loc[self.out.day_type == "weekday", "day_type_epdo_per_1000_trips"].max(), self.source.loc[self.source.weekday_high_flow, "weekday_epdo_per_1000_trips"].max())

    def test_19_above_q99_does_not_clip(self):
        value = self.out.day_type_epdo_per_1000_trips.max()
        row = self.out.loc[self.out.day_type_epdo_per_1000_trips.idxmax()]
        self.assertEqual(row.day_type_epdo_per_1000_trips, value)

    def test_20_physical_segment_fk_integrity(self):
        self.assertTrue(set(self.out.physical_segment_id).issubset(set(self.source.physical_segment_id)))

    def test_21_combined_long_form_conservation(self):
        self.assertEqual(len(self.out), int(self.source.weekday_high_flow.sum() + self.source.holiday_high_flow.sum()))

    def test_22_overlap_conservation(self):
        result = overlap_counts(self.source)
        self.assertEqual(result, {"weekday_only": 1, "holiday_only": 1, "both": 2, "neither": 2})

    def test_23_no_risk_rank(self):
        self.assertFalse(any("rank" in c.lower() for c in self.out.columns))

    def test_24_no_hotspot_flag(self):
        self.assertFalse(any("hotspot" in c.lower() for c in self.out.columns))

    def test_25_no_new_exposure_cutoff(self):
        self.assertFalse(any("minimum_exposure" in c.lower() for c in self.out.columns))

    def test_26_row_reorder_fingerprint(self):
        self.assertEqual(presentation_fingerprint(self.out), presentation_fingerprint(self.out.sample(frac=1, random_state=3)))

    def test_27_upstream_mismatch_fails_closed(self):
        with self.assertRaisesRegex(SpatialContractError, "receipt mismatch"):
            validate_locked_inputs({}, {}, "bad", "bad", 0)

    def test_28_figure_generation_is_deterministic(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            first = render_figures(self.out, Path(a), self.source); second = render_figures(self.out, Path(b), self.source)
            self.assertEqual([sha256_file(x) for x in first], [sha256_file(x) for x in second])

    def test_29_geoparquet_metadata_and_reread(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "presentation.parquet"; write_geoparquet(path, self.out)
            metadata = pq.read_schema(path).metadata
            geo = json.loads(metadata[b"geo"])
            self.assertEqual(geo["primary_column"], "geometry")
            self.assertEqual(geo["columns"]["geometry"]["crs"]["id"]["code"], 4326)
            validate_presentation(pd.read_parquet(path), self.source)

    def test_30_class_counts_conserve_by_day(self):
        counts = counts_by_day(self.out, "cbi_display_class", CBI_LABELS)
        self.assertEqual(sum(counts["weekday"].values()), 3)
        self.assertEqual(sum(counts["holiday"].values()), 3)


if __name__ == "__main__":
    unittest.main()
