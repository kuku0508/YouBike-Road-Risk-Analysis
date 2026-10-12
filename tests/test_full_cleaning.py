import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from clean_real_month import (ALLOWLIST_VERSION, FULL_PERIOD_MONTHS, PARSER_VERSION,
                              PIPELINE_VERSION, config_from_profile, expected_issue_count,
                              profile_expectations, sha256_file)
from run_full_cleaning import profile_issue_count, validate_reusable

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "notes/data-quality-profile.json"
MANIFEST = ROOT / "notes/full-period-cleaning-manifest.json"


class FullPeriodCleaningContractTests(unittest.TestCase):
    def test_scope_is_exactly_twenty_seven_ordered_months(self):
        self.assertEqual(len(FULL_PERIOD_MONTHS), 27)
        self.assertEqual(FULL_PERIOD_MONTHS[0], "2023/01")
        self.assertEqual(FULL_PERIOD_MONTHS[-1], "2025/03")

    def test_profile_driven_config_supports_header_and_schema_variants(self):
        january = config_from_profile(PROFILE, "2023/01")
        november = config_from_profile(PROFILE, "2024/11")
        march = config_from_profile(PROFILE, "2025/03")
        self.assertEqual((january["schema"], january["bike_type"]),
                         ("v1_6col", {"<NULL>": 2_686_167}))
        self.assertEqual((november["schema"], november["bike_type"]), ("v2_7col", None))
        self.assertEqual((march["schema"], march["records"]), ("v2_7col", 6_208_631))

    def test_resume_requires_identity_and_output_hashes(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder); partition = base / "partition"; partition.mkdir()
            raw = base / "raw.zip"; raw.write_bytes(b"raw")
            allowlist = base / "allowlist.csv"; allowlist.write_bytes(b"rules")
            cleaned = partition / "cleaned.parquet"; cleaned.write_bytes(b"clean")
            quarantine = partition / "quarantine.jsonl"; quarantine.write_bytes(b"")
            receipt_path = base / "receipt.json"
            receipt = {
                "period": "2023/01", "dry_run": False,
                "pipeline_version": PIPELINE_VERSION,
                "parser_version": PARSER_VERSION,
                "allowlist_version": ALLOWLIST_VERSION,
                "allowlist_sha256": sha256_file(allowlist), "validation_status": "passed",
                "raw_source": {"sha256": sha256_file(raw)},
                "output_hashes": {"cleaned.parquet": sha256_file(cleaned),
                                  "quarantine.jsonl": sha256_file(quarantine)},
            }
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            reused = validate_reusable(receipt_path, partition, raw, allowlist, "2023/01")
            self.assertEqual(reused["period"], "2023/01")
            cleaned.write_bytes(b"changed")
            with self.assertRaisesRegex(Exception, "output hash mismatch"):
                validate_reusable(receipt_path, partition, raw, allowlist, "2023/01")

    def test_sparse_monthly_issue_map_treats_omitted_key_as_zero(self):
        monthly = profile_expectations(PROFILE, "2024-08")["monthly"]
        self.assertNotIn("duration_zero", monthly["issue_counts"])
        self.assertEqual(expected_issue_count(monthly, "duration_zero"), 0)
        self.assertEqual(expected_issue_count(monthly, "duration_gt_24h"), 488)

    def test_aggregate_issue_count_reads_structured_profile_value(self):
        profile = json.loads(PROFILE.read_text(encoding="utf-8"))["extended_report_period"]
        self.assertEqual(profile_issue_count(profile, "origin_missing"), 272)
        self.assertEqual(profile_issue_count(profile, "duration_gt_24h"), 7_856)
        self.assertEqual(profile_issue_count(profile, "not_present"), 0)

    @unittest.skipUnless(MANIFEST.exists(), "formal full-period manifest is not present")
    def test_formal_manifest_is_complete_and_conserved(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        global_counts = manifest["global"]
        self.assertEqual((manifest["status"], manifest["month_count"]), ("complete", 27))
        self.assertEqual(global_counts["total_input_records"], 109_713_899)
        self.assertEqual(global_counts["total_input_records"],
                         global_counts["total_accepted_records"] +
                         global_counts["total_quarantine_records"])
        self.assertEqual(global_counts["total_quarantine_records"], 127)
        self.assertTrue(all(manifest["phase3a_cross_checks"].values()))


if __name__ == "__main__":
    unittest.main()
