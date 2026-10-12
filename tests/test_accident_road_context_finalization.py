import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.finalize_accident_road_context import (
    CRS_ASSUMPTION,
    OUTPUT_COLUMNS,
    SpatialContractError,
    assert_receipt_fingerprint,
    candidate_feature_index,
    classify_context,
    final_output_fingerprint,
    stable_receipt_fingerprint,
    validate_final_context,
)
from src.validate_accident_road_reference import atomic_parquet, sha256_file


def bounded(status, count, indexes="[]", nearest=None):
    return pd.Series({
        "containment_status": status,
        "contained_polygon_count": count,
        "candidate_feature_indexes_json": indexes,
        "nearest_distance_m": nearest,
    })


def final_row(accident_id, status, road_id=None, road_name=None, town_name=None):
    spatial = status != "coordinate_unavailable"
    return {
        "reconstructed_accident_id": accident_id,
        "year": 2023,
        "event_datetime": "2023-01-01T00:00",
        "x_raw": "121.5" if spatial else None,
        "y_raw": "25" if spatial else None,
        "x_epsg3826": 300000.0 if spatial else None,
        "y_epsg3826": 2770000.0 if spatial else None,
        "road_context_status": status,
        "road_id": road_id,
        "road_name": road_name,
        "town_name": town_name,
        "road_reference_feature_count": 1 if status.startswith("contained_") and status != "contained_multiple" else (2 if status == "contained_multiple" else 0),
        "crs_assumption": CRS_ASSUMPTION,
        "source_accident_entity_fingerprint": "entity",
        "source_bounded_validation_fingerprint": "bounded",
        "source_road_reference_fingerprint": "road",
    }


class AccidentRoadContextFinalizationTests(unittest.TestCase):
    def test_01_valid_unique_polygon(self):
        status = classify_context(bounded("contained_unique", 1, "[0]"), {"road_id": "A", "road_name": "路", "town_name": "區"})
        self.assertEqual(status, ("contained_valid_road", "A", "路", "區"))

    def test_02_blank_road_id(self):
        status = classify_context(bounded("contained_unique", 1, "[0]"), {"road_id": "", "road_name": "路", "town_name": "區"})
        self.assertEqual(status, ("contained_blank_road_id", None, "路", "區"))

    def test_03_outside_reference(self):
        self.assertEqual(classify_context(bounded("contained_zero", 0), None)[0], "outside_reference_coverage")

    def test_04_missing_coordinate(self):
        self.assertEqual(classify_context(bounded("coordinate_unavailable", 0), None)[0], "coordinate_unavailable")

    def test_05_multiple_is_preserved(self):
        result = classify_context(bounded("contained_multiple", 2, "[0,1]"), None)
        self.assertEqual(result, ("contained_multiple", None, None, None))

    def test_06_near_outside_is_not_attributed(self):
        result = classify_context(bounded("contained_zero", 0, nearest=0.5), None)
        self.assertEqual(result[0], "outside_reference_coverage")
        self.assertIsNone(result[1])

    def test_07_blank_id_with_name_stays_null(self):
        result = classify_context(bounded("contained_unique", 1, "[0]"), {"road_id": "", "road_name": "南京東路", "town_name": "中山區"})
        self.assertIsNone(result[1])

    def test_08_road_name_never_substitutes_id(self):
        result = classify_context(bounded("contained_unique", 1, "[0]"), {"road_id": "", "road_name": "A-001", "town_name": "區"})
        self.assertEqual(result[0], "contained_blank_road_id")
        self.assertIsNone(result[1])

    def test_09_status_conservation(self):
        statuses = ["contained_valid_road", "contained_blank_road_id", "outside_reference_coverage", "coordinate_unavailable", "contained_multiple"]
        frame = pd.DataFrame([final_row(str(i), status, "A" if status == "contained_valid_road" else None, "路" if status in {"contained_valid_road", "contained_blank_road_id"} else None, "區" if status in {"contained_valid_road", "contained_blank_road_id"} else None) for i, status in enumerate(statuses)], columns=OUTPUT_COLUMNS)
        counts = {status: 1 for status in statuses}
        self.assertEqual(validate_final_context(frame, set(frame.reconstructed_accident_id), expected_rows=5, expected_counts=counts), counts)

    def test_10_id_set_equality(self):
        frame = pd.DataFrame([final_row("a", "contained_valid_road", "A", "路", "區")], columns=OUTPUT_COLUMNS)
        with self.assertRaises(SpatialContractError):
            validate_final_context(frame, {"different"}, expected_rows=1, expected_counts={status: int(status == "contained_valid_road") for status in ["contained_valid_road", "contained_blank_road_id", "outside_reference_coverage", "coordinate_unavailable", "contained_multiple"]})

    def test_11_row_order_does_not_change_fingerprint(self):
        frame = pd.DataFrame([final_row("b", "contained_valid_road", "A", "路", "區"), final_row("a", "outside_reference_coverage")], columns=OUTPUT_COLUMNS)
        self.assertEqual(final_output_fingerprint(frame), final_output_fingerprint(frame.iloc[::-1]))

    def test_12_bounded_receipt_mismatch_fails_closed(self):
        receipt = {"value": 1}
        receipt["receipt_fingerprint_sha256"] = stable_receipt_fingerprint(receipt)
        with self.assertRaises(SpatialContractError):
            assert_receipt_fingerprint(receipt, "not-the-recorded-fingerprint")

    def test_13_crs_assumption_is_explicit(self):
        self.assertIn("operationally treated as EPSG:4326", CRS_ASSUMPTION)
        self.assertIn("EPSG:3826", CRS_ASSUMPTION)

    def test_14_multiple_never_tie_breaks(self):
        result = classify_context(bounded("contained_multiple", 3, "[0,1,2]"), None)
        self.assertIsNone(result[1])

    def test_15_deterministic_parquet_output(self):
        frame = pd.DataFrame([final_row("a", "contained_valid_road", "A", "路", "區")], columns=OUTPUT_COLUMNS)
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.parquet"
            second = Path(directory) / "second.parquet"
            atomic_parquet(first, frame)
            atomic_parquet(second, frame)
            self.assertEqual(sha256_file(first), sha256_file(second))

    def test_16_candidate_feature_count_must_match(self):
        with self.assertRaises(SpatialContractError):
            candidate_feature_index(bounded("contained_unique", 1, "[]"))


if __name__ == "__main__":
    unittest.main()
