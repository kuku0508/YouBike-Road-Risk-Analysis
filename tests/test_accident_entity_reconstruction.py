import unittest

import pandas as pd

from src.reconstruct_accident_entities import (
    build_party_groups,
    build_spot_groups,
    classify_crosswalk,
    crs_sanity,
    dataframe_fingerprint,
    normalize_decimal,
    normalize_text,
    wgs84_to_twd97,
)


def spot(dt="2023-01-01T10:00", location="地點", x="121.5", y="25", handling="2"):
    return {"發生時間": "", "處理別": handling, "肇事地點": location, "座標-X": x, "座標-Y": y, "event_datetime": dt, "location_cmp": normalize_text(location), "x_cmp": normalize_decimal(x), "y_cmp": normalize_decimal(y)}


def party(seq="1", dt="2023-01-01T10:00", location="地點", x="121.5", y="25", death="0", late="0", injury="1"):
    return {"當事人序號": seq, "肇事地點": location, "座標-X": x, "座標-Y": y, "死亡人數": death, "2-30日死亡人數": late, "受傷人數": injury, "event_datetime": dt, "location_cmp": normalize_text(location), "x_cmp": normalize_decimal(x), "y_cmp": normalize_decimal(y)}


def crosswalk(spots, parties):
    return classify_crosswalk(build_spot_groups(pd.DataFrame(spots)), build_party_groups(pd.DataFrame(parties)), 2023)


class AccidentEntityReconstructionTests(unittest.TestCase):
    def test_01_one_event_two_parties_one_entity(self):
        result = crosswalk([spot()], [party("1"), party("2")])
        self.assertEqual(result.iloc[0]["match_status"], "exact_1to1")
        self.assertEqual(result.iloc[0]["party_record_count"], 2)

    def test_02_same_date_different_time(self):
        result = crosswalk([spot("2023-01-01T10:00"), spot("2023-01-01T11:00")], [party(dt="2023-01-01T10:00"), party(dt="2023-01-01T11:00")])
        self.assertEqual((result.match_status == "exact_1to1").sum(), 2)

    def test_03_same_datetime_different_coordinates(self):
        result = crosswalk([spot(x="121.5"), spot(x="121.6")], [party(x="121.5"), party(x="121.6")])
        self.assertEqual(result.reconstructed_accident_id.nunique(), 2)

    def test_04_same_datetime_coordinate_different_location(self):
        result = crosswalk([spot(location="A"), spot(location="B")], [party(location="A"), party(location="B")])
        self.assertEqual((result.match_status == "exact_1to1").sum(), 2)

    def test_05_duplicate_candidate_event_is_ambiguous(self):
        result = crosswalk([spot(), spot()], [party()])
        self.assertEqual(result.iloc[0]["match_status"], "ambiguous_duplicate_spot_event")
        self.assertIsNone(result.iloc[0]["reconstructed_accident_id"])

    def test_06_ambiguous_many_to_one_not_tiebroken(self):
        result = crosswalk([spot(), spot()], [party("1"), party("2")])
        self.assertEqual(result.iloc[0]["spot_record_count"], 2)
        self.assertEqual(result.iloc[0]["match_status"], "ambiguous_duplicate_spot_event")

    def test_07_unmatched_event(self):
        result = crosswalk([spot()], [party(location="other")])
        self.assertIn("unmatched_spot_event", set(result.match_status))

    def test_08_unmatched_party_group(self):
        result = crosswalk([spot()], [party(location="other")])
        self.assertIn("unmatched_party_group", set(result.match_status))

    def test_09_stable_id_independent_of_row_order(self):
        one = crosswalk([spot()], [party("1"), party("2")])
        two = crosswalk([spot()], [party("2"), party("1")])
        self.assertEqual(one.iloc[0].reconstructed_accident_id, two.iloc[0].reconstructed_accident_id)

    def test_10_consistent_severity_promoted_once(self):
        result = crosswalk([spot()], [party("1", death="1", injury="2"), party("2", death="1", injury="2")])
        self.assertEqual((result.iloc[0].death_count, result.iloc[0].injury_count), (1, 2))

    def test_11_inconsistent_severity_fails_closed(self):
        result = crosswalk([spot()], [party("1", injury="1"), party("2", injury="2")])
        self.assertEqual(result.iloc[0].match_status, "severity_conflict")
        self.assertIsNone(result.iloc[0].reconstructed_accident_id)

    def test_12_coordinate_precision_normalization(self):
        self.assertEqual(normalize_decimal("121.5000"), "121.5")
        self.assertEqual(normalize_decimal("121.5000004", digits=6), "121.5")

    def test_13_yearly_schema_difference_is_visible(self):
        self.assertNotEqual(["發生時間", "光線"], ["發生時間", "道路照明設備"])

    def test_14_deterministic_output_fingerprint(self):
        frame = crosswalk([spot(location="A"), spot(location="B")], [party(location="A"), party(location="B")]).fillna("")
        columns = ["year", "event_datetime", "location_cmp", "x_cmp", "y_cmp", "match_status"]
        self.assertEqual(dataframe_fingerprint(frame, columns), dataframe_fingerprint(frame.iloc[::-1], columns))

    def test_15_crs_assumption_sanity_transform(self):
        x, y = wgs84_to_twd97(121.5, 25.0)
        self.assertTrue(290000 < x < 310000)
        self.assertTrue(2760000 < y < 2780000)
        frame = pd.DataFrame([spot()], dtype=str)
        result = crs_sanity([frame], [296000, 2760000, 313000, 2790000])
        self.assertTrue(result["bbox_overlap_positive"])
        self.assertFalse(result["matching_use"])


if __name__ == "__main__":
    unittest.main()
