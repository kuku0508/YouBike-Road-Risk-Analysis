import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RoutingContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract=json.loads((ROOT/"config/routing_contract.yaml").read_text(encoding="utf-8"))
        cls.receipt=json.loads((ROOT/"notes/brouter-contract-validation.json").read_text(encoding="utf-8"))

    def test_od_source_hash_gate(self):
        p=ROOT/self.contract["od_input"]["path"]
        self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),self.contract["od_input"]["sha256"])
    def test_exact_station_coordinate_join(self): self.assertEqual(self.contract["station_coordinates"]["join_key"],"exact_station_id")
    def test_missing_coordinate_fails_closed(self):
        self.assertIn("otherwise unresolved",self.contract["station_coordinates"]["fallback_source"])
        final=json.loads((ROOT/"notes/routing-coordinate-finalization-receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(final["unresolved_conflict_count"],3)
    def test_conflict_override_preserves_provenance(self):
        self.assertIn("preserve provenance flag",self.contract["station_coordinates"]["conflicting_coordinate_policy"])
        final=json.loads((ROOT/"notes/routing-coordinate-finalization-receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(final["accepted_conflict_count"]+final["unresolved_conflict_count"],31)
    def test_conflicting_coordinate_fails_closed(self): self.assertEqual(len(self.receipt["coordinate_audit"]["conflicting_station_ids"]),31)
    def test_self_loop_policy(self): self.assertEqual(self.receipt["od"]["self_loop_edges"],1504)
    def test_brouter_identity_is_pinned(self): self.assertEqual(len(self.contract["brouter"]["jar_sha256"]),64)
    def test_graph_identity_is_pinned(self): self.assertEqual(len(self.contract["routing_graph"]["sha256"]),2)
    def test_directed_od_preserved(self): self.assertEqual(self.contract["route_directionality"].split(";")[0],"directed")
    def test_reciprocal_independent(self): self.assertIn("independently",self.contract["route_directionality"])
    def test_failure_taxonomy_matches(self): self.assertEqual(set(self.contract["failure_taxonomy"]),{"success","self_loop_not_routed","missing_coordinate","coordinate_conflict","no_route","brouter_error","malformed_output","snap_anomaly","timeout"})
    def test_cache_identity_complete(self):
        self.assertEqual(set(self.contract["cache_key_fields"]),{"origin_station_id","destination_station_id","origin_coordinate","destination_coordinate","brouter_version","routing_graph_hashes","trekking_profile_hash","routing_contract_version","coordinate_artifact_hash","routing_parameters"})
    def test_sample_selection_deterministic_hash(self):
        sample=self.receipt["bounded_sample"]["definition"]
        h=hashlib.sha256(json.dumps(sample,sort_keys=True,separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(h,self.receipt["bounded_sample"]["sha256"])
    def test_full_routing_remains_false(self): self.assertFalse(self.contract["full_routing_execution"]); self.assertFalse(self.receipt["full_routing_executed"])
    def test_status_is_blocked_not_ready(self): self.assertTrue(self.receipt["validation_status"].startswith("blocked_"))


if __name__ == "__main__": unittest.main()
