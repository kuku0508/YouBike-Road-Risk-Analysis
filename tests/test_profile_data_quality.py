import csv
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from profile_data_quality import byte_key, illegal_byte_count, profile


class Phase3ProfilerTests(unittest.TestCase):
    def test_byte_key_is_unambiguous_and_lossless(self):
        self.assertNotEqual(byte_key(["ab", "c"]), byte_key(["a", "bc"]))
        value = b"bad\xff".decode("utf-8", "surrogateescape")
        self.assertEqual(illegal_byte_count(value), 1)
        self.assertIn(b"\xff", byte_key([value]))

    def test_small_profile_keeps_repeats_and_separates_categories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "raw"
            raw.mkdir()
            archive = raw / "202301_YouBike2.0票證刷卡資料.zip"
            rows = [
                ["rent_time", "rent_station", "return_time", "return_station", "rent", "infodate"],
                ["2023-01-01 10:00:00", "A", "2023-01-01 10:00:00", "B", "0:00:00", "2023-01-01"],
                ["2023-01-01 10:00:00", "A", "2023-01-01 10:00:00", "B", "0:00:00", "2023-01-01"],
                ["bad", "", "2023-01-02 11:00:00", "C_1", "25:00:00", "2023-01-02"],
            ]
            csv_path = root / "sample.csv"
            with csv_path.open("w", encoding="utf-8", newline="") as handle:
                csv.writer(handle).writerows(rows)
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(csv_path, "sample.csv")
            index = root / "index.csv"
            index.write_text(
                "名稱,資料集識別碼,UpdateTime,SrcUpdateTime,fileinfo,fileURL\n"
                "臺北市公共自行車,379530000H,2023-02-01T00:00:00+08:00,2023-02-01T00:00:00+08:00,2023/1/1,https://example.invalid/sample.zip\n",
                encoding="cp950",
            )
            output = profile(("2023-01",), raw, index, root / "profile.sqlite")

            self.assertEqual(output["total_records"], 3)
            self.assertEqual(output["category_unions"]["invalid"]["count"], 1)
            self.assertEqual(output["category_unions"]["quality_issue"]["count"], 1)
            self.assertEqual(output["issue_counts"]["duration_zero"]["count"], 2)
            self.assertEqual(output["repeated_identical"]["repeated_groups"], 1)
            self.assertEqual(output["repeated_identical"]["involved_records"], 2)
            self.assertEqual(output["repeated_identical"]["excess_copies"], 1)
            self.assertEqual(output["repeated_identical"]["policy"], "retain_all")
            self.assertEqual(output["bike_type"]["v1_structural_absence"], 3)
            self.assertFalse(output["method"]["cleaning_performed"])


if __name__ == "__main__":
    unittest.main()
