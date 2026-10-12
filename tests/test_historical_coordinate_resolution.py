import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from src.resolve_historical_station_coordinates import (
    LEDGER_COLUMNS, classify_station, dataframe_fingerprint, displacement_bin,
    haversine_m, month_bounds, sha256_file,
)


ROOT = Path(__file__).resolve().parents[1]


class HistoricalCoordinateResolutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = json.loads((ROOT / "config/historical_coordinate_resolution_policy.yaml").read_text(encoding="utf-8"))
        cls.receipt = json.loads((ROOT / "notes/historical-coordinate-resolution-receipt.json").read_text(encoding="utf-8"))

    def evidence(self, rows):
        return pd.DataFrame(rows, columns=LEDGER_COLUMNS)

    def observed(self, first="2024-06-01", last="2024-12-31"):
        return pd.Series({"station_id": "S", "station_name": "Station", "city": "Taipei",
                          "first_observed_date": first, "last_observed_date": last})

    def row(self, date, lon=121.5, lat=25.0):
        return {"station_id":"S", "station_name":"Station", "city":"Taipei", "latitude":lat, "longitude":lon,
                "source_name":date, "source_url_or_reference":"x", "source_date":date, "snapshot_date":date,
                "valid_from":None, "valid_to":None, "source_type":"snapshot", "official_status":"official",
                "retrieval_date":"2026-09-19", "source_hash":"h", "evidence_notes":""}

    def test_initial_counts_reproduced(self):
        self.assertEqual(self.receipt["initial_coordinate_status"], {"routing_nodes":2782,"dated_2024_05_31":1384,"coordinate_conflicts":31,"current_only":1367})

    def test_ledger_schema(self): self.assertEqual(len(LEDGER_COLUMNS), 16)
    def test_exact_station_id_only(self): self.assertEqual(self.policy["station_identity_rule"], "exact_station_id_only")
    def test_source_hash_gate(self): self.assertEqual(len(self.receipt["historical_sources_used"][0]["sha256"]), 64)
    def test_current_only_not_accepted(self):
        result=classify_station(self.evidence([self.row("2026-09-13")]), self.observed())
        self.assertFalse(result["accepted"])
    def test_direct_historical_tier_is_accepted_by_policy(self): self.assertIn("tier_1_direct_historical", self.policy["accepted_evidence_tiers"])
    def test_temporal_bracketing_tier2(self):
        result=classify_station(self.evidence([self.row("2024-05-31"),self.row("2026-09-13")]), self.observed())
        self.assertTrue(result["accepted"]); self.assertEqual(result["evidence_tier"],"tier_2_temporally_bracketed_stable")
    def test_conflict_fails_closed(self):
        result=classify_station(self.evidence([self.row("2024-05-31"),self.row("2026-09-13",lon=121.51)]), self.observed())
        self.assertFalse(result["accepted"]); self.assertEqual(result["coordinate_status"],"unresolved_conflict")
    def test_geodesic_distance(self): self.assertGreater(haversine_m((121.5,25.0),(121.5001,25.0)), 9)
    def test_observed_month_bounds(self): self.assertEqual(month_bounds("2024/02"),("2024-02-01","2024-02-29"))
    def test_evidence_does_not_cover_pre_snapshot(self):
        result=classify_station(self.evidence([self.row("2024-05-31"),self.row("2026-09-13")]), self.observed("2023-01-01"))
        self.assertFalse(result["accepted"]); self.assertEqual(result["coordinate_status"],"partially_covered")
    def test_outside_period_relocation_requires_evidence(self): self.assertEqual(self.policy["relocation_handling"]["outside_period"],"use evidenced in-period coordinate")
    def test_inside_period_relocation_requires_eras(self): self.assertEqual(self.policy["relocation_handling"]["within_period"],"construct_non_overlapping_coordinate_eras")
    def test_era_overlap_prohibited(self): self.assertIn("non-overlapping",self.policy["routing_readiness_rule"])
    def test_exact_one_era_semantics(self): self.assertIn("uniquely",self.policy["routing_readiness_rule"])
    def test_duplicate_coordinate_ids_not_merged(self): self.assertEqual(self.policy["station_identity_rule"],"exact_station_id_only")
    def test_unresolved_preserved(self): self.assertTrue(self.receipt["artifacts"]["unresolved_artifact"]["rows"] > 0)
    def test_edge_coverage_bounded(self): self.assertLessEqual(self.receipt["routing_readiness"]["od_edge_coverage"],1)
    def test_trip_coverage_bounded(self): self.assertLessEqual(self.receipt["routing_readiness"]["trip_weight_coverage"],1)
    def test_contract_not_bumped_without_established_era(self): self.assertEqual(self.receipt["routing_contract_version"],"road-routing-contract-v1")
    def test_artifact_fingerprint_deterministic(self):
        frame=pd.DataFrame({"station_id":["b","a"],"routing_lat":[2,1],"routing_lon":[4,3]})
        self.assertEqual(dataframe_fingerprint(frame,["station_id","routing_lat","routing_lon"]),dataframe_fingerprint(frame.iloc[::-1],["station_id","routing_lat","routing_lon"]))
    def test_hashes_are_pinned(self):
        files = [ROOT/"data/raw/station_snapshot_2024-05-31.csv", ROOT/"data/raw/youbike_immediate_2026-09-13.json", ROOT/"data/raw/new_taipei_youbike_2026-09-14.csv"]
        self.assertEqual([sha256_file(path) for path in files], [x["sha256"] for x in self.receipt["historical_sources_used"]])
    def test_full_routing_not_triggered(self): self.assertFalse(self.receipt["full_routing_executed"])
    def test_displacement_bins(self):
        self.assertEqual(displacement_bin(0),"exact_same"); self.assertEqual(displacement_bin(100),"gte_100m")


if __name__ == "__main__": unittest.main()
