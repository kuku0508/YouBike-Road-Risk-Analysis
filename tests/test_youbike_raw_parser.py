import base64
import sys
import tempfile
import unittest
from pathlib import Path
import zipfile

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from youbike_raw_parser import (
    CANONICAL_COLUMNS,
    SchemaDetectionError,
    SchemaValidationError,
    UnsafeForSerializationError,
    iter_path,
    parse_bytes,
    require_serialization_safe,
)


FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_bytes()


class YouBikeRawParserTests(unittest.TestCase):
    def assert_canonical(self, record, version, source_row, bike_type):
        self.assertEqual(tuple(key for key in record if not key.startswith("_")), CANONICAL_COLUMNS)
        self.assertEqual(record["_schema_version"], version)
        self.assertEqual(record["_source_row"], source_row)
        self.assertEqual(record["bike_type"], bike_type)

    def test_six_columns_with_header(self):
        records = parse_bytes(fixture("six_header.csv"), "six_header.csv")
        self.assertEqual(len(records), 1)
        self.assert_canonical(records[0], "v1_6col", 2, None)
        self.assertEqual(records[0]["origin_station_raw"], "起點_1")

    def test_six_columns_without_header(self):
        record = parse_bytes(fixture("six_no_header.csv"))[0]
        self.assert_canonical(record, "v1_6col", 1, None)

    def test_seven_columns_with_header(self):
        record = parse_bytes(fixture("seven_header.csv"))[0]
        self.assert_canonical(record, "v2_7col", 2, "電輔車")

    def test_seven_columns_without_header(self):
        record = parse_bytes(fixture("seven_no_header.csv"))[0]
        self.assert_canonical(record, "v2_7col", 1, "一般車")

    def test_invalid_utf8_is_lossless_and_blocks_serialization(self):
        payload = bytes.fromhex(fixture("invalid_utf8.csv.hex").decode("ascii").strip())
        record = parse_bytes(payload)[0]
        self.assertEqual(len(record["_parse_warnings"]), 1)
        warning = record["_parse_warnings"][0]
        self.assertEqual(warning["field"], "origin_station_raw")
        self.assertEqual(base64.b64decode(warning["field_bytes_base64"]), "起點".encode() + b"\xff")
        self.assertEqual(record["origin_station_raw"].encode("utf-8", "surrogateescape"), "起點".encode() + b"\xff")
        with self.assertRaises(UnicodeEncodeError):
            record["origin_station_raw"].encode("utf-8", "strict")
        with self.assertRaises(UnsafeForSerializationError):
            require_serialization_safe(record)

    def test_unknown_width_fails_closed(self):
        with self.assertRaisesRegex(SchemaDetectionError, "unknown field count"):
            parse_bytes(fixture("unknown_width.csv"))

    def test_malformed_header_fails_closed(self):
        with self.assertRaisesRegex(SchemaDetectionError, "resembles a header"):
            parse_bytes(fixture("malformed_header.csv"))

    def test_unknown_bike_type_fails_closed(self):
        payload = fixture("seven_no_header.csv").replace("一般車".encode(), "未知車".encode())
        with self.assertRaisesRegex(SchemaDetectionError, "unrecognised bike_type"):
            parse_bytes(payload)

    def test_later_schema_violation_fails_closed(self):
        payload = fixture("six_no_header.csv") + b"2023-11-02 00:00:00,A,2023-11-02 01:00:00,B,00:01:00,extra,2023-11-02\n"
        with self.assertRaisesRegex(SchemaValidationError, "expected 6 fields"):
            parse_bytes(payload)

    def test_impossible_calendar_date_fails_closed(self):
        payload = fixture("six_no_header.csv").replace(b"2023-11-01", b"2023-02-30")
        with self.assertRaisesRegex(SchemaDetectionError, "calendar date/time"):
            parse_bytes(payload)

    def test_clean_record_is_serialization_safe(self):
        record = parse_bytes(fixture("seven_no_header.csv"))[0]
        self.assertIsNone(require_serialization_safe(record))

    def test_single_csv_zip_is_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "month.zip"
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("month.csv", fixture("six_no_header.csv"))
            record = list(iter_path(path))[0]
        self.assertEqual(record["_schema_version"], "v1_6col")
        self.assertEqual(record["_source_file"], "month.zip::month.csv")


if __name__ == "__main__":
    unittest.main()
