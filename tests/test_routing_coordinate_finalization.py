import hashlib
import json
import unittest
from pathlib import Path

import pandas as pd

from src.finalize_routing_coordinates import ASSUMPTION_ID, coordinate_sequences


ROOT = Path(__file__).resolve().parents[1]


class RoutingCoordinateFinalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assumption = json.loads((ROOT/"config/routing_coordinate_assumption.yaml").read_text(encoding="utf-8"))
        cls.receipt = json.loads((ROOT/"notes/routing-coordinate-finalization-receipt.json").read_text(encoding="utf-8"))
        cls.contract = json.loads((ROOT/"config/routing_contract.yaml").read_text(encoding="utf-8"))
        cls.final = pd.read_parquet(ROOT/"data/processed/routing/routing_station_coordinates_2023_2024.parquet")
        cls.gaps = pd.read_csv(ROOT/"data/processed/routing/core_routing_coordinate_gap.csv", dtype={"station_id":str})
        cls.unroutable = pd.read_parquet(ROOT/"data/processed/routing/unroutable_od_due_to_coordinate_gap.parquet")
        cls.conflicts = pd.read_parquet(ROOT/"data/interim/routing/routing_coordinate_conflicts.parquet")

    def test_01_legacy_source_hash_gate(self):
        p=ROOT/self.assumption["source"]["path"]
        self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),self.assumption["source"]["sha256"])
    def test_02_mapping_hash_gate(self):
        p=ROOT/self.assumption["source"]["mapping_path"]
        self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),self.assumption["source"]["mapping_sha256"])
    def test_03_prior_provenance_conclusion_preserved(self):
        prior=json.loads((ROOT/"notes/legacy-coordinate-recovery-receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(prior["readiness_status"],"LEGACY HISTORICAL COORDINATES: NOT SUFFICIENTLY TRACEABLE")
    def test_04_evidence_and_acceptance_are_separate(self):
        self.assertEqual(set(self.final.evidence_status),{"supporting_unverified_provenance"})
        self.assertEqual(set(self.final.routing_acceptance),{"accepted_by_analyst_assumption"})
    def test_05_override_is_source_scoped(self):
        self.assertEqual(set(self.final.source_sha256),{self.assumption["source"]["sha256"]})
    def test_06_exact_canonical_mapping_is_unique(self):
        self.assertFalse(self.final.station_id.duplicated().any())
    def test_07_verified_precedence_is_declared(self):
        self.assertTrue(self.assumption["coordinate_precedence"][0].startswith("verified_direct"))
    def test_08_legacy_coordinate_selection(self):
        self.assertTrue(self.final[["routing_lat","routing_lon"]].notna().all().all())
    def test_09_all_31_conflicts_preserved(self):
        self.assertEqual(int(self.final.coordinate_conflict.sum())+int(self.gaps.coordinate_conflict.sum()),31)
        self.assertEqual(len(self.conflicts),31)
    def test_10_current_only_not_silently_accepted(self):
        self.assertNotIn("current_only",set(self.final.coordinate_source))
    def test_11_monthly_change_detection(self):
        x=pd.DataFrame({"station_id":["a","a"],"legacy_month":["2023-01","2023-02"],"longitude":[121.5,121.6],"latitude":[25.0,25.0]})
        self.assertTrue(coordinate_sequences(x).iloc[0].coordinate_era_required)
    def test_12_coordinate_era_trigger_absent_for_final_source(self):
        self.assertEqual(self.receipt["coordinate_era_count"],0)
        self.assertIsNone(self.receipt["artifacts"]["coordinate_era"])
    def test_13_stable_coordinate_collapse(self):
        self.assertEqual(len(self.final),self.final.station_id.nunique())
    def test_14_core_coverage(self):
        self.assertEqual(len(self.final)+len(self.gaps),2782)
    def test_15_od_edge_coverage(self):
        c=self.receipt["coverage"]
        self.assertEqual(c["routable_non_self_od_edges"]+c["unroutable_non_self_od_edges"],c["total_non_self_od_edges"])
    def test_16_trip_weight_coverage(self):
        c=self.receipt["coverage"]
        self.assertEqual(c["routable_trip_weight"]+c["unroutable_trip_weight"],c["total_non_self_trip_weight"])
    def test_17_unresolved_od_preserved(self):
        self.assertEqual(len(self.unroutable),self.receipt["coverage"]["unroutable_non_self_od_edges"])
    def test_18_self_loop_policy_unchanged(self):
        self.assertEqual(self.receipt["self_loops"],{"edges":1504,"trip_weight":6023568,"policy":"excluded_from_BRouter_and_retained_in_conservation_accounting"})
    def test_19_cross_city_od_retained(self):
        self.assertTrue((self.unroutable.origin_city != self.unroutable.destination_city).any())
    def test_20_final_artifact_hash(self):
        p=ROOT/self.receipt["artifacts"]["final_coordinate"]["path"]
        self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),self.receipt["artifacts"]["final_coordinate"]["sha256"])
    def test_21_coordinate_change_invalidates_cache(self):
        self.assertIn("coordinate artifact hash",self.receipt["cache_invalidation"])
        self.assertIn("routing_contract_version",self.contract["cache_key_fields"])
    def test_22_no_full_routing(self):
        self.assertFalse(self.receipt["full_routing_executed"])
        self.assertFalse(self.contract["full_routing_execution"])
    def test_23_identity_mapping_not_equal_coordinate_acceptance(self):
        self.assertEqual(self.receipt["identity_mapped_station_count"],2769)
        self.assertEqual(self.receipt["accepted_under_assumption_count"],2756)
    def test_24_no_fuzzy_or_suffix_rule(self):
        self.assertIn("no fuzzy",self.assumption["identity_gate"])
        self.assertIn("suffix-stripping",self.assumption["identity_gate"])


if __name__ == "__main__": unittest.main()
