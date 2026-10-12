import csv
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from station_cleaning_contract import RepairContractError, apply_station_contract, load_allowlist


ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = ROOT / "config/station_repair_allowlist.csv"
VERSION = "station-repair-policy-v2"


class StationCleaningContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = load_allowlist(ALLOWLIST, VERSION)
        with ALLOWLIST.open(encoding="utf-8-sig", newline="") as stream:
            cls.rows = list(csv.DictReader(stream))

    def example(self, decision=None, subtype=None):
        return next(row for row in self.rows
                    if (decision is None or row["decision"] == decision)
                    and (subtype is None or row["tier1_subtype"] == subtype))

    def raw(self, row):
        import base64
        return base64.b64decode(row["raw_value_base64"]).decode("utf-8", errors="surrogateescape")

    def test_tier_1a_1b_1c_apply_exactly(self):
        for subtype in ("1A", "1B", "1C"):
            row = self.example("approved_repair", subtype)
            result = apply_station_contract(self.raw(row), self.rules)
            self.assertEqual(result["station_clean"], row["canonical_station_name"])
            self.assertEqual(result["tier1_subtype"], subtype)
            self.assertEqual(result["station_raw"], self.raw(row))
            self.assertTrue(result["evidence_sources"])

    def test_nonapproved_values_remain_unchanged(self):
        for decision in ("candidate_only", "ambiguous", "unresolved"):
            row = self.example(decision)
            raw = self.raw(row)
            result = apply_station_contract(raw, self.rules)
            self.assertEqual(result["station_clean"], raw)
            self.assertEqual(result["station_raw"], raw)
            self.assertEqual(result["repair_status"], decision)

    def test_unknown_value_has_no_fuzzy_fallback_and_suffix_is_preserved(self):
        raw = "完全未知站_1"
        result = apply_station_contract(raw, self.rules)
        self.assertEqual(result["station_raw"], raw)
        self.assertEqual(result["station_clean"], raw)
        self.assertEqual(result["repair_status"], "unchanged_no_rule")

    def test_missing_version_fails_closed(self):
        with self.assertRaises(RepairContractError):
            load_allowlist(ALLOWLIST, "")

    def test_conflicting_approved_rules_fail_closed(self):
        fieldnames = list(self.rows[0])
        base = dict(self.example("approved_repair"))
        conflict = dict(base); conflict["canonical_station_id"] = "conflicting-id"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "rules.csv"
            with path.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fieldnames)
                writer.writeheader(); writer.writerows([base, conflict])
            with self.assertRaises(RepairContractError):
                load_allowlist(path, VERSION)

    def test_destination_only_classification_is_not_a_repair_rule(self):
        with (ROOT / "notes/station-universe-classification.csv").open(encoding="utf-8-sig", newline="") as stream:
            destination = next(row for row in csv.DictReader(stream) if row["decision"] == "not_an_error")
        raw = self.raw(destination)
        result = apply_station_contract(raw, self.rules)
        self.assertNotEqual(result["repair_status"], "approved_repair")


if __name__ == "__main__":
    unittest.main()
