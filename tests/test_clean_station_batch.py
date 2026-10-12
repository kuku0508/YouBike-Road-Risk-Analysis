import csv
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from clean_station_batch import (ALLOWLIST_VERSION, BatchContractError, clean_record,
                                 load_station_universe, run_partition, sha256_file)
from station_cleaning_contract import RepairContractError, load_allowlist

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests/fixtures/cleaning"
STAMP = "2026-09-16T00:00:00+00:00"


class CleanStationBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = load_allowlist(FIX / "allowlist.csv", ALLOWLIST_VERSION)
        cls.universe = load_station_universe(FIX / "station-universe.jsonl")
        cls.records = {r["case"]: r for r in
                       (json.loads(line) for line in (FIX / "input.jsonl").read_text(encoding="utf-8").splitlines())}

    def clean(self, case):
        return clean_record(self.records[case], self.rules, self.universe)

    def test_01_tier1a_origin(self):
        row = self.clean("tier1a_origin")
        self.assertEqual((row["origin_station_clean"], row["origin_station_tier1_subtype"]),
                         ("合成完整站A", "1A"))

    def test_02_tier1b_destination(self):
        row = self.clean("tier1b_destination")
        self.assertEqual((row["destination_station_clean"], row["destination_station_tier1_subtype"]),
                         ("合成完整站B", "1B"))

    def test_03_tier1c(self):
        self.assertEqual(self.clean("dual_tier1c_tier1a")["origin_station_tier1_subtype"], "1C")

    def test_04_both_ends_repair(self):
        row = self.clean("dual_tier1c_tier1a")
        self.assertEqual(row["origin_station_repair_status"], "approved_repair")
        self.assertEqual(row["destination_station_repair_status"], "approved_repair")

    def test_05_tier2_preserves_raw(self):
        row = self.clean("tier2_origin")
        self.assertEqual(row["origin_station_raw"], row["origin_station_clean"])
        self.assertEqual(row["origin_station_repair_status"], "candidate_only")

    def test_06_ambiguous_preserves_raw(self):
        row = self.clean("ambiguous_destination")
        self.assertEqual(row["destination_station_raw"], row["destination_station_clean"])
        self.assertEqual(row["destination_station_repair_status"], "ambiguous")

    def test_07_unresolved_preserves_raw(self):
        row = self.clean("unresolved_origin")
        self.assertEqual(row["origin_station_raw"], row["origin_station_clean"])
        self.assertEqual(row["origin_station_repair_status"], "unresolved")

    def test_08_unknown_has_no_fuzzy_match(self):
        row = self.clean("both_no_rule")
        self.assertEqual(row["origin_station_repair_status"], "unchanged_no_rule")

    def test_09_not_an_error_is_not_repaired(self):
        row = self.clean("cross_city")
        self.assertEqual(row["destination_station_repair_status"], "not_an_error")
        self.assertEqual(row["destination_station_city"], "New Taipei")

    def test_10_suffixes_are_preserved(self):
        row = self.clean("suffixes")
        self.assertEqual((row["origin_station_clean"], row["destination_station_clean"]),
                         ("合法站_1", "合法站_2"))

    def test_11_six_column_bike_type_is_null(self):
        self.assertIsNone(self.clean("six_col_null")["bike_type"])

    def test_12_approved_illegal_bytes_are_safe_and_traceable(self):
        row = self.clean("approved_illegal")
        self.assertEqual(row["origin_station_clean"], "合成完整站C")
        self.assertIn("\\xe5", row["origin_station_raw"])
        self.assertNotIn("�", row["origin_station_raw"])
        self.assertEqual(row["origin_station_raw_base64"], "5ZCI5oiQ6Z2e5rOV5Q==")

    def test_13_unapproved_illegal_bytes_are_not_replaced(self):
        with self.assertRaisesRegex(BatchContractError, "serialization_unsafe"):
            self.clean("unapproved_illegal")

    def mutated_allowlist(self, mutate, duplicate=False):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "allowlist.csv"
        with (FIX / "allowlist.csv").open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream)); fields = list(rows[0])
        target = next(row for row in rows if row["decision"] == "approved_repair")
        mutate(target)
        if duplicate:
            conflict = dict(target); conflict["canonical_station_id"] = "SYN-CONFLICT"; rows.append(conflict)
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
        return path

    def test_14_rule_conflict_fails_closed(self):
        path = self.mutated_allowlist(lambda row: None, duplicate=True)
        with self.assertRaises(RepairContractError): load_allowlist(path, ALLOWLIST_VERSION)

    def test_15_version_mismatch_fails_closed(self):
        with self.assertRaises(RepairContractError): load_allowlist(FIX / "allowlist.csv", "wrong-version")

    def test_16_missing_evidence_fails_closed(self):
        path = self.mutated_allowlist(lambda row: row.update(evidence_sources=""))
        with self.assertRaises(RepairContractError): load_allowlist(path, ALLOWLIST_VERSION)

    def test_17_missing_station_id_fails_closed(self):
        path = self.mutated_allowlist(lambda row: row.update(canonical_station_id=""))
        with self.assertRaises(RepairContractError): load_allowlist(path, ALLOWLIST_VERSION)

    def run_once(self, root, run_id="synthetic-run"):
        return run_partition(FIX / "input.jsonl", FIX / "allowlist.csv",
                             FIX / "station-universe.jsonl", root, run_id, STAMP)

    def test_18_record_conservation_and_quarantine(self):
        with tempfile.TemporaryDirectory() as folder:
            receipt = self.run_once(Path(folder))
            self.assertEqual((receipt["input_record_count"], receipt["cleaned_record_count"],
                              receipt["quarantine_record_count"]), (13, 12, 1))
            self.assertTrue(receipt["record_conservation"])

    def test_19_partition_failure_leaves_no_partial_output(self):
        path = self.mutated_allowlist(lambda row: row.update(evidence_sources=""))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaises(RepairContractError):
                run_partition(FIX / "input.jsonl", path, FIX / "station-universe.jsonl",
                              root, "failed", STAMP)
            self.assertFalse((root / "year=synthetic/month=01").exists())
            self.assertEqual(list(root.rglob(".staging-*")), [])

    def test_20_receipt_hashes_and_counts_are_reproducible(self):
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
            a, b = self.run_once(Path(one)), self.run_once(Path(two))
            self.assertEqual(a, b)

    def test_21_raw_value_and_parser_provenance_always_exist(self):
        for case in self.records:
            if case == "unapproved_illegal": continue
            row = self.clean(case)
            for side in ("origin", "destination"):
                self.assertTrue(row[f"{side}_station_raw"])
                self.assertTrue(row[f"{side}_station_raw_base64"])
            for key in ("_source_file", "_source_row", "_schema_version", "_parse_warnings"):
                self.assertIn(key, row)

    def test_22_phase33_allowlist_and_evidence_are_immutable(self):
        lock = json.loads((FIX / "phase33-lock.json").read_text(encoding="utf-8"))
        self.assertEqual({name: sha256_file(ROOT / name) for name in lock}, lock)

    def test_parquet_roundtrip_preserves_null_strings_and_provenance(self):
        import pyarrow.parquet as pq
        with tempfile.TemporaryDirectory() as folder:
            self.run_once(Path(folder))
            records = pq.ParquetFile(Path(folder) / "year=synthetic/month=01/cleaned.parquet").read().to_pylist()
            self.assertEqual(len(records), 12)
            self.assertTrue(any(r["bike_type"] is None for r in records))
            self.assertTrue(all("_source_file" in r for r in records))
            self.assertTrue(any(r["origin_station_clean"] == "合成完整站C" for r in records))


if __name__ == "__main__":
    unittest.main()
