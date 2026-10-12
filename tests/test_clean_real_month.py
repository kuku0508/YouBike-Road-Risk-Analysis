import base64
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from clean_real_month import (EXPECTED_RAW_SHA256, EXPECTED_RECORDS, MultisetFingerprint,
                              RUN_CONFIGS, combine_fingerprints, load_station_universe_csv,
                              parser_to_execution, sha256_file, validate_parquet)
from clean_station_batch import _write_parquet, clean_record, load_station_universe
from station_cleaning_contract import load_allowlist

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "notes/2023-11-cleaning-dry-run-receipt.json"
PARQUET = ROOT / "data/processed/dry_run/year=2023/month=11/cleaned.parquet"
RECEIPT_2024 = ROOT / "notes/2024-11-cleaning-dry-run-receipt.json"
PARQUET_2024 = ROOT / "data/processed/dry_run/year=2024/month=11/cleaned.parquet"
QUARANTINE_2024 = ROOT / "data/processed/dry_run/year=2024/month=11/quarantine.jsonl"


class RealMonthCleaningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))

    def test_receipt_source_schema_and_conservation_gates(self):
        r = self.receipt
        self.assertEqual(r["period"], "2023/11")
        self.assertEqual(r["raw_source"]["sha256"], EXPECTED_RAW_SHA256)
        self.assertEqual(r["input_records"], EXPECTED_RECORDS)
        self.assertEqual(r["input_records"], r["accepted_records"] + r["quarantine_records"])
        self.assertTrue(r["record_conservation"])
        self.assertEqual(r["preflight"]["schema_version"], "v1_6col")
        self.assertFalse(r["preflight"]["header_present"])
        self.assertEqual(r["preflight"]["warning_record_count"], 0)
        self.assertTrue(all(r["preflight"]["gates"].values()))

    def test_receipt_status_grains_reconcile(self):
        r = self.receipt
        for side in ("origin", "destination"):
            self.assertEqual(sum(r["station_side_status_counts"][side].values()), r["accepted_records"])
        self.assertEqual(sum(r["trip_level_repair_counts"].values()), r["accepted_records"])
        approved_sides = sum(r["station_side_status_counts"][side]["approved_repair"]
                             for side in ("origin", "destination"))
        self.assertEqual(sum(r["tier1_subtype_station_side_counts"].values()), approved_sides)

    def test_structural_null_and_repeated_policy_are_preserved(self):
        r = self.receipt
        self.assertEqual(r["parquet_validation"]["bike_type_null_count"], EXPECTED_RECORDS)
        self.assertTrue(r["repeated_identical_preservation"]["raw_multiset_fingerprint_match"])
        self.assertEqual(r["repeated_identical_preservation"]["policy"], "retain_all")
        self.assertEqual(r["repeated_identical_preservation"]["repeated_groups"], 5059)

    def test_allowlist_and_phase_evidence_hashes_remain_fixed(self):
        expected = {
            "config/station_repair_allowlist.csv": "9699e5e25b975fec202e58e5bf8727578f34075953ff961314b029b18e1bff1a",
            "notes/data-quality-profile.json": "85310e4b4852b4ec7d7e73d20aa2f684d32ced2da14bfa1022f25b4d9e4241ce",
            "notes/station-name-forensics.csv": "4ad0c82385628ad4d045fbe4c2935980b10d8be845e6bf4bcfbcfeee031ae26f",
            "notes/station-name-forensics-evidence.json": "0119d76a2f37abd54c9631935c31a6869f722103e06f0d09bc75959c23099734",
            "notes/station-repair-policy-evidence.json": "29d1a19bd8ad67129ce1caefb2ed78d05ce3ec404306720b6b13e5df6ba4d7ab",
        }
        self.assertEqual({name: sha256_file(ROOT / name) for name in expected}, expected)
        self.assertEqual(self.receipt["allowlist_sha256"], expected["config/station_repair_allowlist.csv"])

    def test_parser_adapter_preserves_empty_raw_station_as_exact_bytes(self):
        record = {"origin_station_raw": "", "destination_station_raw": "合成站"}
        adapted = parser_to_execution(record)
        self.assertEqual(adapted["origin_station_raw_base64"], "")
        self.assertEqual(base64.b64decode(adapted["destination_station_raw_base64"]).decode(), "合成站")

    def test_multiset_fingerprint_is_order_independent_and_count_sensitive(self):
        rows = [{"borrow_time":"a", "origin_station_raw":"b", "return_time":"c",
                 "destination_station_raw":"d", "duration_raw":"e", "bike_type":None,
                 "borrow_date":"f"},
                {"borrow_time":"g", "origin_station_raw":"h", "return_time":"i",
                 "destination_station_raw":"j", "duration_raw":"k", "bike_type":None,
                 "borrow_date":"l"}]
        a = MultisetFingerprint(); b = MultisetFingerprint()
        for row in rows: a.add(row)
        for row in reversed(rows): b.add(row)
        self.assertEqual(a.as_dict(), b.as_dict())
        b.add(rows[0]); self.assertNotEqual(a.as_dict(), b.as_dict())

    def test_2024_config_preserves_real_bike_type_contract(self):
        self.assertEqual(RUN_CONFIGS["2024/11"]["schema"], "v2_7col")
        self.assertEqual(RUN_CONFIGS["2024/11"]["bike_type"],
                         {"一般車": 5_733_169, "電輔車": 149_933})

    def test_quarantine_fingerprint_combines_with_illegal_approved_parquet(self):
        import tempfile
        fixture = ROOT / "tests/fixtures/cleaning"
        rules = load_allowlist(fixture / "allowlist.csv", "station-repair-policy-v2")
        universe = load_station_universe(fixture / "station-universe.jsonl")
        rows = {row["case"]: row for row in map(json.loads,
                (fixture / "input.jsonl").read_text(encoding="utf-8").splitlines())}

        def raw_record(row):
            result = dict(row)
            for side in ("origin", "destination"):
                result[f"{side}_station_raw"] = base64.b64decode(
                    row[f"{side}_station_raw_base64"]).decode("utf-8", "surrogateescape")
            return result

        approved = raw_record(rows["approved_illegal"])
        unsafe = raw_record(rows["unapproved_illegal"])
        approved["_source_row"] = 1; unsafe["_source_row"] = 2
        approved_input = dict(rows["approved_illegal"]); approved_input["_source_row"] = 1
        accepted = clean_record(approved_input, rules, universe)
        accepted_fp = MultisetFingerprint(); accepted_fp.add(approved)
        quarantine_fp = MultisetFingerprint(); quarantine_fp.add(unsafe)
        combined = combine_fingerprints(accepted_fp.as_dict(), quarantine_fp.as_dict())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cleaned.parquet"; _write_parquet([accepted], path)
            validation = validate_parquet(path, 1, combined, [2], quarantine_fp.as_dict(), 2,
                                          {"一般車": 1})
        self.assertEqual(validation["combined_multiset_fingerprint"], combined)
        self.assertEqual(validation["bike_type_counts"], {"一般車": 1})
        self.assertNotEqual(validation["bike_type_counts"], {"一般車": 2})

    def test_station_universe_loads_only_not_an_error(self):
        universe = load_station_universe_csv(ROOT / "notes/station-universe-classification.csv")
        self.assertEqual(len(universe), 1311)
        self.assertTrue(all(row["classification"] == "not_an_error" for row in universe.values()))

    @unittest.skipUnless(PARQUET.exists(), "ignored real-month dry-run output is not present")
    def test_local_parquet_matches_receipt_and_full_invariants(self):
        r = self.receipt
        self.assertEqual(sha256_file(PARQUET), r["output_hashes"]["cleaned.parquet"])
        validation = validate_parquet(PARQUET, r["accepted_records"],
                                      r["preflight"]["raw_multiset_fingerprint"], [])
        self.assertEqual(validation["row_count"], r["accepted_records"])
        self.assertEqual(validation["clean_changes_without_approval"], 0)
        expected = dict(r["preflight"]["phase3_station_patterns"])
        expected.update(origin_missing=r["preflight"]["origin_missing"],
                        destination_missing=r["preflight"]["destination_missing"])
        self.assertEqual(validation["raw_station_profile"], expected)


@unittest.skipUnless(RECEIPT_2024.exists(), "2024/11 dry-run receipt is not present")
class AdversarialRealMonthCleaningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt = json.loads(RECEIPT_2024.read_text(encoding="utf-8"))

    def test_2024_source_schema_bike_and_encoding_gates(self):
        r = self.receipt
        self.assertEqual((r["period"], r["input_records"], r["preflight"]["schema_version"]),
                         ("2024/11", 5_883_102, "v2_7col"))
        self.assertFalse(r["preflight"]["header_present"])
        self.assertEqual(r["bike_type_counts"], {"一般車": 5_733_169, "電輔車": 149_933})
        self.assertTrue(all(r["preflight"]["gates"].values()))
        self.assertEqual(r["illegal_utf8"]["illegal_byte_count"], 25_720)
        self.assertEqual(r["illegal_utf8"]["affected_field_count"], 20_944)
        self.assertEqual(r["illegal_utf8"]["affected_record_count"], 20_217)

    def test_2024_conservation_status_and_illegal_breakdown(self):
        r = self.receipt; illegal = r["illegal_utf8"]
        self.assertEqual(r["input_records"], r["accepted_records"] + r["quarantine_records"])
        self.assertEqual((r["accepted_records"], r["quarantine_records"]), (5_883_088, 14))
        self.assertEqual(sum(r["accepted_bike_type_counts"].values()), r["accepted_records"])
        self.assertEqual(sum(r["quarantine_bike_type_counts"].values()), r["quarantine_records"])
        self.assertEqual(illegal["approved_repair_accepted_station_sides"], 20_930)
        self.assertEqual(illegal["approved_repair_accepted_records"], 20_203)
        self.assertEqual(illegal["unapproved_quarantine_records"], 14)
        self.assertEqual(illegal["unapproved_quarantine_station_sides"], 14)
        self.assertEqual(illegal["approved_repair_accepted_station_sides"] +
                         illegal["unapproved_quarantine_station_sides"], illegal["affected_field_count"])
        self.assertEqual(r["quarantine_reason_counts"],
                         {"serialization_unsafe_unapproved_destination_station_raw": 14})

    def test_2024_repeated_and_repair_grains_reconcile(self):
        r = self.receipt
        for side in ("origin", "destination"):
            self.assertEqual(sum(r["station_side_status_counts"][side].values()), r["accepted_records"])
        self.assertEqual(sum(r["trip_level_repair_counts"].values()), r["accepted_records"])
        approved = sum(r["station_side_status_counts"][side]["approved_repair"]
                       for side in ("origin", "destination"))
        self.assertEqual(sum(r["tier1_subtype_station_side_counts"].values()), approved)
        repeated = r["repeated_identical_preservation"]
        self.assertEqual((repeated["repeated_groups"], repeated["involved_records"],
                          repeated["excess_copies"]), (17_918, 36_264, 18_346))
        self.assertTrue(repeated["raw_multiset_fingerprint_match"])

    @unittest.skipUnless(PARQUET_2024.exists() and QUARANTINE_2024.exists(),
                         "ignored 2024/11 outputs are not present")
    def test_2024_local_outputs_match_receipt_and_full_invariants(self):
        r = self.receipt
        self.assertEqual(sha256_file(PARQUET_2024), r["output_hashes"]["cleaned.parquet"])
        self.assertEqual(sha256_file(QUARANTINE_2024), r["output_hashes"]["quarantine.jsonl"])
        quarantine = [json.loads(line) for line in QUARANTINE_2024.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(quarantine), 14)
        qfp = MultisetFingerprint()
        for item in quarantine:
            raw = item["raw_record"]
            for side in ("origin", "destination"):
                raw[f"{side}_station_raw"] = base64.b64decode(
                    raw[f"{side}_station_raw_base64"]).decode("utf-8", "surrogateescape")
            qfp.add(raw)
        validation = validate_parquet(PARQUET_2024, r["accepted_records"],
            r["preflight"]["raw_multiset_fingerprint"],
            [item["source_provenance"]["_source_row"] for item in quarantine],
            qfp.as_dict(), r["input_records"], r["accepted_bike_type_counts"])
        self.assertEqual(validation["combined_multiset_fingerprint"],
                         r["preflight"]["raw_multiset_fingerprint"])
        self.assertEqual(validation["clean_changes_without_approval"], 0)
        self.assertEqual(validation["approved_missing_provenance"], 0)
        self.assertEqual(validation["nonapproved_identity_assignments"], 0)


if __name__ == "__main__":
    unittest.main()
