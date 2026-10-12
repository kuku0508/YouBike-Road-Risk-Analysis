import csv
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from design_station_repair_policy import classify_mapping


class StationRepairPolicyTests(unittest.TestCase):
    def setUp(self):
        self.forensic = {"months": "2024-09"}
        self.current = [{"name": "完整站名", "id": "1", "city": "Taipei",
                         "source": "taipei_current_2026-09-13"}]

    def test_current_metadata_alone_is_tier_2(self):
        tier, decision, *_ = classify_mapping(self.forensic, self.current, {})
        self.assertEqual((tier, decision), ("Tier 2", "candidate_only"))

    def test_tier_1_requires_temporal_or_historical_evidence(self):
        tier, decision, evidence, *_ = classify_mapping(
            self.forensic, self.current, {"完整站名": {"2024-10"}})
        self.assertEqual((tier, decision), ("Tier 1", "approved_repair"))
        self.assertTrue(evidence)

    def test_ambiguous_and_unresolved_are_never_approved(self):
        competitor = {**self.current[0], "name": "完整站名二", "id": "2"}
        self.assertEqual(classify_mapping(self.forensic, self.current + [competitor], {})[1], "ambiguous")
        self.assertEqual(classify_mapping(self.forensic, [], {})[1], "unresolved")

    def test_committed_allowlist_invariants(self):
        root = Path(__file__).resolve().parents[1]
        with (root / "config/station_repair_allowlist.csv").open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        approved = [row for row in rows if row["decision"] == "approved_repair"]
        self.assertTrue(approved)
        self.assertTrue(all(row["evidence_tier"] == "Tier 1" for row in approved))
        self.assertTrue(all(row["historical_evidence"] and row["evidence_sources"] for row in approved))
        self.assertFalse(any(row["evidence_tier"] == "Tier 1" for row in rows
                             if row["decision"] in {"ambiguous", "unresolved"}))

    def test_raw_value_and_numeric_suffix_are_not_normalized(self):
        raw = "合法站_1"
        forensic = {"months": "2024-09", "raw_station_value": raw}
        before = dict(forensic)
        classify_mapping(forensic, self.current, {"完整站名": {"2024-09"}})
        self.assertEqual(forensic, before)
        self.assertEqual(forensic["raw_station_value"], "合法站_1")

    def test_old_evidence_is_immutable_and_destination_only_is_not_repair(self):
        root = Path(__file__).resolve().parents[1]
        evidence = json.loads((root / "notes/station-repair-policy-evidence.json").read_text(encoding="utf-8"))
        self.assertEqual(evidence["immutability"]["before"], evidence["immutability"]["after"])
        for path, digest in evidence["immutability"]["after"].items():
            self.assertEqual(hashlib.sha256((root / path).read_bytes()).hexdigest(), digest)
        with (root / "notes/station-universe-classification.csv").open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertFalse(any(row["decision"] == "approved_repair" for row in rows))
        self.assertTrue(all(row["historical_operational_status"] == "unresolved" for row in rows))


if __name__ == "__main__":
    unittest.main()
