import base64
import json
import unittest
from collections import defaultdict
from pathlib import Path

import pandas as pd

from src.recover_legacy_station_coordinates import (
    CORE_MONTHS, b64, build_mapping, coordinate_eras_from_month_coords,
    count_illegal_utf8, parse_coordinate, parse_legacy, parse_month, raw_bytes,
)
from src.resolve_historical_station_coordinates import sha256_file


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/active_station_all.csv"


class LegacyCoordinateRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt = json.loads((ROOT / "notes/legacy-coordinate-recovery-receipt.json").read_text(encoding="utf-8"))
        cls.frame, cls.audit = parse_legacy(RAW)

    def test_01_raw_csv_hash_gate(self):
        self.assertEqual(sha256_file(RAW), self.receipt["source"]["sha256"])

    def test_02_malformed_utf8_is_lossless(self):
        data = RAW.read_bytes(); decoded = data.decode("utf-8", "surrogateescape")
        self.assertEqual(raw_bytes(decoded), data)
        self.assertGreater(count_illegal_utf8(data)[0], 0)
        self.assertFalse(self.audit["strict_utf8_valid"])

    def test_03_month_extraction(self):
        self.assertEqual(parse_month("youbike_202301"), "2023-01")
        self.assertIsNone(parse_month("2023-01"))

    def test_04_core_month_completeness(self):
        observed = sorted(self.frame[self.frame.month.isin(CORE_MONTHS)].month.unique())
        self.assertEqual(observed, CORE_MONTHS)

    def test_05_coordinate_validation(self):
        self.assertEqual(parse_coordinate("121.5", latitude=False), 121.5)
        self.assertIsNone(parse_coordinate("NA", latitude=True))
        self.assertIsNone(parse_coordinate("999", latitude=True))

    def test_06_legacy_number_is_not_canonical_id(self):
        self.assertEqual(self.audit["legacy_number_looks_canonical_id_rows"], 0)

    @staticmethod
    def one_name_frame(name="站A"):
        return pd.DataFrame({"station_name_raw_base64":[b64(name)], "station_name_raw":[name], "month":["2023-01"],
                             "longitude":[121.5], "latitude":[25.0], "has_illegal_utf8":[False]})

    def test_07_exact_name_unique_mapping(self):
        result = build_mapping(self.one_name_frame(), {"站A":{"500000001"}}, {}, {}, {}, {"500000001":"Taipei"})
        self.assertTrue(result.iloc[0].identity_accepted)

    def test_08_ambiguous_exact_name_fails_closed(self):
        result = build_mapping(self.one_name_frame(), {"站A":{"500000001","500000002"}}, {}, {}, {}, {})
        self.assertEqual(result.iloc[0].mapping_status, "ambiguous")
        self.assertFalse(result.iloc[0].identity_accepted)

    def test_09_known_alias_mapping(self):
        result = build_mapping(self.one_name_frame("舊名"), {}, {}, {"舊名":{"500000001"}}, {}, {"500000001":"Taipei"})
        self.assertEqual(result.iloc[0].mapping_status, "known_alias_candidate")

    def test_10_fuzzy_candidate_not_accepted(self):
        result = build_mapping(self.one_name_frame("站A相似"), {"站A":{"500000001"}}, {}, {}, {}, {})
        self.assertEqual(result.iloc[0].mapping_status, "unmatched")

    def test_11_suffix_is_not_stripped(self):
        result = build_mapping(self.one_name_frame("站A_1"), {"站A":{"500000001"}}, {}, {}, {}, {})
        self.assertEqual(result.iloc[0].mapping_status, "unmatched")

    def test_12_provenance_gate(self):
        self.assertEqual(self.receipt["provenance"]["evidence_acceptance"], "supporting_only; cannot independently make a station routing-ready")

    def test_13_monthly_coordinate_timeline(self):
        self.assertEqual(self.receipt["coordinates"]["stability_status_counts"], {"stable_exact_coordinate":2769})

    def test_14_conflicting_coordinates_are_preserved(self):
        eras = coordinate_eras_from_month_coords({"2023-01":(121.5,25.0), "2023-02":(121.6,25.1)})
        self.assertEqual(len(eras), 2)

    def test_15_temporal_coverage(self):
        self.assertEqual(self.receipt["coordinates"]["temporally_complete_supporting_station_count"], 2743)

    def test_16_within_period_relocation_detection_is_not_claimed(self):
        self.assertEqual(self.receipt["coordinates"]["confirmed_within_period_relocations"], 0)

    def test_17_coordinate_era_construction_nonoverlap(self):
        eras = coordinate_eras_from_month_coords({"2023-01":(1,1),"2023-02":(1,1),"2023-03":(2,2)})
        self.assertEqual(eras, [{"first_month":"2023-01","last_month":"2023-02","coordinate":(1,1)},
                                {"first_month":"2023-03","last_month":"2023-03","coordinate":(2,2)}])

    def test_18_phase8a_ledger_integration(self):
        artifact = self.receipt["artifacts"]["combined_evidence_ledger"]
        self.assertEqual(artifact["rows"], 4193 + self.receipt["artifacts"]["legacy_evidence"]["rows"])
        self.assertEqual(sha256_file(ROOT / artifact["path"]), artifact["sha256"])

    def test_19_node_coverage_remains_fail_closed(self):
        self.assertEqual(self.receipt["routing_readiness_after"]["routing_ready_nodes"], 5)

    def test_20_od_edge_coverage_remains_fail_closed(self):
        self.assertEqual(self.receipt["routing_readiness_after"]["routing_ready_non_self_od_edges"], 0)

    def test_21_trip_weight_coverage_remains_fail_closed(self):
        self.assertEqual(self.receipt["routing_readiness_after"]["routing_ready_non_self_trip_weight"], 0)

    def test_22_deterministic_hashes_and_fingerprints(self):
        for artifact in self.receipt["artifacts"].values():
            if "path" in artifact and artifact["path"].startswith("data/interim"):
                self.assertEqual(sha256_file(ROOT / artifact["path"]), artifact["sha256"])
        self.assertTrue(all(len(value) == 64 for value in self.receipt["deterministic_fingerprints"].values()))

    def test_23_no_phase81_routing_triggered(self):
        self.assertFalse(self.receipt["full_routing_executed"])

    def test_24_conflicts_are_not_silently_resolved(self):
        self.assertEqual(self.receipt["phase8a_conflicts"]["total"], 31)
        self.assertEqual(self.receipt["phase8a_conflicts"]["resolved_for_routing"], 0)


if __name__ == "__main__":
    unittest.main()
