import base64
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from station_name_forensics import candidate_rows, choose_mapping, display, raw_bytes


class StationNameForensicsTests(unittest.TestCase):
    def test_surrogateescape_base64_round_trip_is_lossless(self):
        source = b"station-\xe5\x8f"
        text = source.decode("utf-8", errors="surrogateescape")
        self.assertEqual(raw_bytes(text), source)
        self.assertEqual(base64.b64decode(base64.b64encode(raw_bytes(text))), source)
        self.assertTrue(display(text).endswith(r"\xe5\x8f"))

    def test_candidate_generation_does_not_mutate_raw_value(self):
        raw = "糖?文化園區"
        metadata = [{"name": "糖廍文化園區", "id": "1", "city": "Taipei", "source": "official"}]
        before = raw
        status, candidate, *_ = choose_mapping(candidate_rows(raw, "question_mark", metadata))
        self.assertEqual(raw, before)
        self.assertEqual(status, "unique_supported")
        self.assertNotEqual(candidate, raw)

    def test_ambiguous_candidates_are_not_promoted(self):
        candidates = [
            {"name": "甲站", "id": "1", "city": "Taipei", "source": "official"},
            {"name": "乙站", "id": "2", "city": "Taipei", "source": "official"},
        ]
        self.assertEqual(choose_mapping(candidates)[0], "ambiguous")

    def test_numeric_suffix_is_preserved(self):
        raw = "合法站_1"
        self.assertEqual(display(raw), "合法站_1")
        self.assertEqual(raw_bytes(raw).decode("utf-8"), raw)

    def test_phase3_evidence_was_not_overwritten(self):
        root = Path(__file__).resolve().parents[1]
        evidence = json.loads((root / "notes/station-name-forensics-evidence.json").read_text(encoding="utf-8"))
        phase3 = root / "notes/data-quality-profile.json"
        digest = hashlib.sha256(phase3.read_bytes()).hexdigest()
        self.assertEqual(evidence["phase3_evidence_sha256_before"], digest)
        self.assertEqual(evidence["phase3_evidence_sha256_after"], digest)


if __name__ == "__main__":
    unittest.main()
