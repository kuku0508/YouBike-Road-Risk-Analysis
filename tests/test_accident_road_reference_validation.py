import unittest

import pandas as pd
from pyproj import CRS, Transformer
from shapely.geometry import Point, Polygon
from shapely.strtree import STRtree

from src.validate_accident_road_reference import (
    SpatialContractError,
    classify_point,
    coordinate_unavailable_relationship,
    coverage_summary,
    require_crs_epsg,
    stable_output_fingerprint,
    validate_geometry_gate,
)


def attribute(index, road_id, name="road", tt="0", intersect=""):
    return {"feature_index": index, "road_id": road_id, "road_name": name, "tt": tt, "intersect": intersect}


def classify(point, geometries, attributes):
    return classify_point(point, STRtree(geometries), geometries, attributes)


def output_row(accident_id, relation):
    return {
        "reconstructed_accident_id": accident_id, "year": 2023,
        "x_raw": "121.5", "y_raw": "25", "x_epsg3826": 300000.0,
        "y_epsg3826": 2770000.0, **relation,
    }


class AccidentRoadReferenceValidationTests(unittest.TestCase):
    def setUp(self):
        self.a = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        self.b = Polygon([(5, 5), (15, 5), (15, 15), (5, 15)])

    def test_01_strictly_inside_unique(self):
        result = classify(Point(2, 2), [self.a], [attribute(0, "A")])
        self.assertEqual(result["containment_status"], "contained_unique")
        self.assertEqual(result["interior_polygon_count"], 1)

    def test_02_boundary_is_covered(self):
        result = classify(Point(0, 5), [self.a], [attribute(0, "A")])
        self.assertEqual(result["containment_status"], "contained_unique")
        self.assertEqual(result["boundary_polygon_count"], 1)

    def test_03_overlap_is_multiple(self):
        result = classify(Point(7, 7), [self.a, self.b], [attribute(0, "A"), attribute(1, "B")])
        self.assertEqual(result["containment_status"], "contained_multiple")
        self.assertEqual(result["interior_polygon_count"], 2)

    def test_04_outside_is_zero(self):
        result = classify(Point(20, 20), [self.a, self.b], [attribute(0, "A"), attribute(1, "B")])
        self.assertEqual(result["containment_status"], "contained_zero")

    def test_05_nearest_distance(self):
        result = classify(Point(12, 2), [self.a, self.b], [attribute(0, "A"), attribute(1, "B")])
        self.assertAlmostEqual(result["nearest_distance_m"], 2.0)

    def test_06_second_nearest_and_gap(self):
        second = Polygon([(20, 0), (30, 0), (30, 10), (20, 10)])
        result = classify(Point(12, 2), [self.a, second], [attribute(0, "A"), attribute(1, "B")])
        self.assertAlmostEqual(result["nearest_distance_m"], 2.0)
        self.assertAlmostEqual(result["second_nearest_distance_m"], 8.0)
        self.assertAlmostEqual(result["distance_gap_m"], 6.0)

    def test_07_equal_distance_tie_not_resolved(self):
        left = Polygon([(0, 0), (2, 0), (2, 2), (0, 2)])
        right = Polygon([(4, 0), (6, 0), (6, 2), (4, 2)])
        result = classify(Point(3, 1), [left, right], [attribute(0, "L"), attribute(1, "R")])
        self.assertEqual(result["nearest_candidate_count"], 2)
        self.assertEqual(result["distance_gap_m"], 0.0)

    def test_08_blank_road_id_is_visible(self):
        result = classify(Point(2, 2), [self.a], [attribute(0, "")])
        self.assertEqual(result["contained_blank_road_id_count"], 1)
        self.assertEqual(result["contained_valid_road_id_count"], 0)

    def test_09_invalid_polygon_fails_closed(self):
        bowtie = Polygon([(0, 0), (2, 2), (0, 2), (2, 0)])
        with self.assertRaises(SpatialContractError):
            validate_geometry_gate([bowtie], [attribute(0, "A")])

    def test_10_empty_geometry_fails_closed(self):
        with self.assertRaises(SpatialContractError):
            validate_geometry_gate([Polygon()], [attribute(0, "A")])

    def test_11_crs_mismatch_fails(self):
        with self.assertRaises(SpatialContractError):
            require_crs_epsg(CRS.from_epsg(4326))

    def test_12_transform_sanity(self):
        x, y = Transformer.from_crs(4326, 3826, always_xy=True).transform(121.5, 25.0)
        self.assertTrue(250000 < x < 350000)
        self.assertTrue(2700000 < y < 2850000)

    def test_13_candidate_ids_are_deterministically_sorted(self):
        result = classify(Point(7, 7), [self.a, self.b], [attribute(0, "B"), attribute(1, "A")])
        self.assertEqual(result["candidate_road_ids_json"], '["A","B"]')

    def test_14_reordered_input_has_identical_fingerprint(self):
        relation = classify(Point(2, 2), [self.a], [attribute(0, "A")])
        first = pd.DataFrame([output_row("b", relation), output_row("a", relation)])
        second = first.iloc[::-1].reset_index(drop=True)
        self.assertEqual(stable_output_fingerprint(first), stable_output_fingerprint(second))

    def test_15_coverage_summary_determinism(self):
        unique = classify(Point(2, 2), [self.a], [attribute(0, "A")])
        zero = classify(Point(20, 20), [self.a, self.b], [attribute(0, "A"), attribute(1, "B")])
        first = pd.DataFrame([output_row("a", unique), output_row("b", zero)])
        second = first.iloc[::-1].reset_index(drop=True)
        self.assertEqual(coverage_summary(first), coverage_summary(second))

    def test_16_missing_coordinate_is_not_called_outside(self):
        result = coordinate_unavailable_relationship()
        self.assertEqual(result["containment_status"], "coordinate_unavailable")
        self.assertIsNone(result["nearest_distance_m"])


if __name__ == "__main__":
    unittest.main()
