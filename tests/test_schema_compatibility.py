import csv
import sys
import tempfile
import unittest
from pathlib import Path
import zipfile

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from audit_schema_compatibility import inspect_month, row_conforms


class SchemaCompatibilityTests(unittest.TestCase):
    def make_zip(self, root, name, rows):
        path = Path(root) / f"{name}.zip"
        csv_path = Path(root) / f"{name}.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as out:
            csv.writer(out).writerows(rows)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(csv_path, csv_path.name)
        return path

    def test_six_and_seven_column_detection(self):
        six = ["2023-01-01 00:00:00", "A", "2023-01-01 01:00:00", "B", "0:05:01", "2023-01-01"]
        seven = ["2025-01-01 00:00:00", "A", "2025-01-01 01:00:00", "B", "0:05:01", "2.0E", "2025-01-01"]
        with tempfile.TemporaryDirectory() as tmp:
            a = inspect_month(self.make_zip(tmp, "six", [six]), "2023-01")
            b = inspect_month(self.make_zip(tmp, "seven", [seven]), "2025-01")
        self.assertEqual(a["dominant_width"], 6)
        self.assertTrue(a["sixth_field_looks_like_date"])
        self.assertFalse(a["vehicle_type_field_exists"])
        self.assertEqual(b["dominant_width"], 7)
        self.assertEqual(b["date_field_position"], 7)
        self.assertTrue(b["vehicle_type_field_exists"])

    def test_header_and_format_detection(self):
        header = ["借車時間", "借車場站", "還車時間", "還車場站", "借用時長", "車種", "借用日期"]
        row = ["2026-01-01 00:00:00", "A", "2026-01-01 01:00:00", "B", "01:00:00", "2.0", "2026-01-01"]
        with tempfile.TemporaryDirectory() as tmp:
            result = inspect_month(self.make_zip(tmp, "header", [header, row]), "2026-01")
        self.assertTrue(result["header_present"])
        self.assertEqual(result["format_nonconforming_rows"], 1)
        self.assertTrue(row_conforms(row))

    def test_invalid_utf8_bytes_are_counted_without_replacement(self):
        row = b"2024-12-01 00:00:00,A\xff,2024-12-01 01:00:00,B,01:00:00,2.0,2024-12-01\r\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "invalid.zip"
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("invalid.csv", row)
            result = inspect_month(path, "2024-12")
        self.assertEqual(result["dominant_width"], 7)
        self.assertEqual(result["undecodable_byte_count"], 1)
        self.assertIn("\\udcff", result["first_rows"][0][1])


if __name__ == "__main__":
    unittest.main()
