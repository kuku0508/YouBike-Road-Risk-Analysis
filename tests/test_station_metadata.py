import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from audit_station_metadata import compare_snapshots, match_group, profile, suffix_pairs


class StationMetadataTests(unittest.TestCase):
    def test_profile_detects_mapping_conflicts_and_missing_validity(self):
        rows = [
            {"station_id": "1", "station_name": "A", "district": "D", "address": "x", "latitude": 1, "longitude": 2},
            {"station_id": "1", "station_name": "A2", "district": "D", "address": "x", "latitude": 1, "longitude": 2},
            {"station_id": "2", "station_name": "A", "district": "D", "address": "y", "latitude": 1, "longitude": 2},
        ]
        result = profile(rows, "test", "https://example.test", "2024-01-01")
        self.assertEqual(result["station_ids_with_multiple_names"]["1"], ["A", "A2"])
        self.assertEqual(result["station_names_with_multiple_ids"]["A"], ["1", "2"])
        self.assertFalse(result["has_valid_from"])

    def test_matching_is_exact_and_non_mutating(self):
        names = ["A_1", "broken?"]
        snapshots = {"s": [{"station_name": "A"}, {"station_name": "A_1"}]}
        result = match_group(names, snapshots)
        self.assertEqual(result["s"]["matched_names"], ["A_1"])
        self.assertEqual(names, ["A_1", "broken?"])

    def test_suffix_pair_keeps_distinct_ids_visible(self):
        snapshots = {"s": [{"station_name": "A", "station_id": "1"},
                           {"station_name": "A_1", "station_id": "2"}]}
        result = suffix_pairs(["A_1"], snapshots)["s"][0]
        self.assertTrue(result["both_present"])
        self.assertTrue(result["ids_are_disjoint"])

    def test_cross_snapshot_comparison_does_not_infer_change_date(self):
        older = [{"station_id": "1", "station_name": "A", "latitude": 1, "longitude": 2}]
        newer = [{"station_id": "1", "station_name": "B", "latitude": 1, "longitude": 3},
                 {"station_id": "2", "station_name": "C", "latitude": 4, "longitude": 5}]
        result = compare_snapshots(older, newer)
        self.assertEqual(result["changed_name_count"], 1)
        self.assertEqual(result["coordinate_changed_count"], 1)
        self.assertEqual(result["only_newer_ids"], 1)
        self.assertIn("do not establish", result["interpretation_limit"])


if __name__ == "__main__":
    unittest.main()
