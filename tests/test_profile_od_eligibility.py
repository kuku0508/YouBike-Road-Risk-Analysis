from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from profile_od_eligibility import _and, _or, classify_endpoint, sha256_file


class ODEligibilityClassificationTests(unittest.TestCase):
    def setUp(self):
        self.evidence = {
            "unique_names": {"Normal": ("T001", "Taipei")},
            "collision_names": {"Collision": [("T002", "Taipei"), ("T003", "Taipei")]},
            "station_universe": {"TkVU": ("N001", "New Taipei")},
        }

    def test_unique_id_paths_and_safe_name_fallback_are_distinct(self):
        self.assertEqual(classify_endpoint("approved_repair", "Damaged", "T009", "RA==", self.evidence)[0],
                         "eligible_unique_id")
        self.assertEqual(classify_endpoint("not_an_error", "NTP", None, "TkVU", self.evidence),
                         ("eligible_unique_id", "N001", "New Taipei"))
        self.assertEqual(classify_endpoint("unchanged_no_rule", "Normal", None, "Tm9ybWFs", self.evidence),
                         ("eligible_unique_id", "T001", "Taipei"))
        self.assertEqual(classify_endpoint("unchanged_no_rule", "Unknown", None, "VW5rbm93bg==", self.evidence)[0],
                         "eligible_valid_name_no_id")

    def test_missing_and_uncertain_classes_fail_closed(self):
        self.assertEqual(classify_endpoint("unchanged_no_rule", "", None, "", self.evidence)[0],
                         "ineligible_missing")
        self.assertEqual(classify_endpoint("unchanged_no_rule", "Collision", None, "Qw==", self.evidence)[0],
                         "ineligible_name_collision")
        self.assertEqual(classify_endpoint("candidate_only", "Candidate", None, "Qw==", self.evidence)[0],
                         "ineligible_candidate_only")
        self.assertEqual(classify_endpoint("ambiguous", "Ambiguous", None, "QQ==", self.evidence)[0],
                         "ineligible_ambiguous")
        self.assertEqual(classify_endpoint("unresolved", "Unresolved", None, "VQ==", self.evidence)[0],
                         "ineligible_unresolved")

    def test_vector_boolean_helpers_are_null_safe(self):
        import pyarrow as pa
        self.assertEqual(_or(pa.array([True, False, None]),
                             pa.array([None, True, False])).to_pylist(), [True, True, False])
        self.assertEqual(_and(pa.array([True, False, None]),
                              pa.array([None, True, True])).to_pylist(), [False, False, False])

    def test_hash_helper_is_stable(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "evidence.bin"; path.write_bytes(b"phase-4")
            self.assertEqual(sha256_file(path),
                             "30c4349f8a382eb6497304b3919ea773386e772f5d6eb4a0aa607a67178654f6")

    def test_machine_policy_has_required_contract_fields(self):
        import json
        policy_path = Path(__file__).resolve().parents[1] / "config/od_inclusion_policy.yaml"
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        required = {"policy_version", "primary_network_boundary", "station_identity_requirement",
                    "allowed_endpoint_statuses", "excluded_endpoint_statuses", "quarantine_behavior",
                    "missing_endpoint_behavior", "candidate_only_behavior", "ambiguous_behavior",
                    "unresolved_behavior", "cross_city_behavior", "repeated_identical_row_behavior",
                    "duration_behavior", "exclusion_precedence", "sensitivity_variants"}
        self.assertFalse(required.difference(policy))
        self.assertEqual(policy["od_node_key"], "station_id")
        self.assertEqual(policy["exclusion_precedence"][0], "quarantined")

    def test_committed_impact_profile_conserves_full_period_records(self):
        import json
        root = Path(__file__).resolve().parents[1]
        impact = json.loads((root / "notes/od-inclusion-impact.json").read_text(encoding="utf-8"))
        policy = json.loads((root / "config/od_inclusion_policy.yaml").read_text(encoding="utf-8"))
        resolved = impact["precedence_resolved_counts"]
        self.assertEqual(sum(resolved.values()), impact["total_input_records"])
        self.assertEqual(
            impact["accepted_cleaned_records"] + impact["quarantine_records"],
            impact["total_input_records"],
        )
        self.assertEqual(
            resolved["od_eligible"],
            impact["policy_variant_retained_records"]["primary_id_required_full_universe"],
        )
        self.assertEqual(impact["policy_version"], policy["policy_version"])


if __name__ == "__main__":
    unittest.main()
