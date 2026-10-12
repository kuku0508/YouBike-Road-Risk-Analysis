import csv
import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path

from src.audit_accident_inputs import (
    AuditError,
    audit_accident_csv,
    audit_road_layer,
    coordinate_audit,
    schema_compatibility,
    stable_receipt_fingerprint,
)


HEADER = ["發生年度", "發生月", "發生日", "發生時-Hours", "發生分", "區序", "肇事地點", "死亡人數", "2-30日死亡人數", "受傷人數", "當事人序號", "車種", "性別", "年齡", "座標-X", "座標-Y"]


def write_csv(path, rows, header=HEADER, encoding="utf-8-sig"):
    with path.open("w", encoding=encoding, newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def make_dbf(path, road_ids=("R1",), invalid_geometry=False):
    fields = [("ROAD_ID", "C", 10, 0), ("ROADNAME", "C", 20, 0), ("TOWNNAME", "C", 9, 0), ("ROADWIDTH", "N", 8, 2), ("TT", "N", 4, 0), ("INTERSECT", "C", 20, 0)]
    count = len(road_ids)
    header_len = 32 + len(fields) * 32 + 1
    record_len = 1 + sum(field[2] for field in fields)
    header = bytearray(32)
    header[0] = 3
    struct.pack_into("<I", header, 4, count)
    struct.pack_into("<H", header, 8, header_len)
    struct.pack_into("<H", header, 10, record_len)
    body = bytearray(header)
    for name, kind, length, decimals in fields:
        descriptor = bytearray(32)
        descriptor[:len(name)] = name.encode("ascii")
        descriptor[11] = ord(kind)
        descriptor[16] = length
        descriptor[17] = decimals
        body.extend(descriptor)
    body.append(13)
    for road_id in road_ids:
        values = [road_id, "Road", "Town", "8.5", "1", "X"]
        record = bytearray(b" ")
        for value, (_, kind, length, _) in zip(values, fields):
            encoded = value.encode("utf-8")
            record.extend(encoded.rjust(length) if kind == "N" else encoded.ljust(length))
        body.extend(record)
    body.append(26)
    path.write_bytes(body)
    return count, invalid_geometry


def make_shapefile(directory, road_ids=("R1",), invalid_geometry=False):
    directory.mkdir()
    count, _ = make_dbf(directory / "Road.dbf", road_ids, invalid_geometry)
    records = []
    for index in range(count):
        points = [(300000.0, 2770000.0), (300010.0, 2770000.0), (300010.0, 2770010.0), (300000.0, 2770010.0)]
        if not invalid_geometry:
            points.append(points[0])
        content = bytearray(struct.pack("<i4d2i", 5, 300000.0, 2770000.0, 300010.0, 2770010.0, 1, len(points)))
        content.extend(struct.pack("<i", 0))
        for point in points:
            content.extend(struct.pack("<2d", *point))
        records.append(bytes(content))
    shp_length = 100 + sum(8 + len(record) for record in records)
    header = bytearray(100)
    struct.pack_into(">i", header, 0, 9994)
    struct.pack_into(">i", header, 24, shp_length // 2)
    struct.pack_into("<i", header, 28, 1000)
    struct.pack_into("<i", header, 32, 5)
    struct.pack_into("<4d", header, 36, 300000.0, 2770000.0, 300010.0, 2770010.0)
    shp = bytearray(header)
    shx = bytearray(header)
    offset_words = 50
    for index, content in enumerate(records, 1):
        shp.extend(struct.pack(">2i", index, len(content) // 2))
        shp.extend(content)
        shx.extend(struct.pack(">2i", offset_words, len(content) // 2))
        offset_words += 4 + len(content) // 2
    struct.pack_into(">i", shx, 24, len(shx) // 2)
    (directory / "Road.shp").write_bytes(shp)
    (directory / "Road.shx").write_bytes(shx)
    (directory / "Road.cpg").write_text("UTF-8", encoding="ascii")
    (directory / "Road.prj").write_text('PROJCS["TWD_1997_TM_Taiwan",PARAMETER["Central_Meridian",121.0]]', encoding="ascii")


class AccidentInputAuditTests(unittest.TestCase):
    def row(self, party="1", x="121.5", y="25.0"):
        return ["112", "01", "02", "03", "04", "01區", "地點", "0", "0", "1", party, "C03", "1", "30", x, y]

    def test_01_normal_accident_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.csv"; write_csv(path, [self.row()])
            result = audit_accident_csv(path)
            self.assertEqual((result["row_count"], result["column_count"]), (1, len(HEADER)))

    def test_02_encoding_issue_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.csv"; path.write_bytes(b"a,b\n1,\xff")
            with self.assertRaises(AuditError): audit_accident_csv(path)

    def test_03_malformed_row_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.csv"; write_csv(path, [["112"]])
            with self.assertRaises(AuditError): audit_accident_csv(path)

    def test_04_missing_coordinate(self):
        frame = audit_frame = __import__("pandas").DataFrame([self.row(x="", y="")], columns=HEADER)
        self.assertEqual(coordinate_audit(audit_frame)["missing_both_coordinate_records"], 1)

    def test_05_invalid_coordinate(self):
        frame = __import__("pandas").DataFrame([self.row(x="bad")], columns=HEADER)
        self.assertEqual(coordinate_audit(frame)["invalid_numeric_coordinate_records"], 1)

    def test_06_duplicate_accident_identifier_is_not_invented(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.csv"; write_csv(path, [self.row("1"), self.row("2")])
            result = audit_accident_csv(path)
            self.assertIn("no explicit", result["accident_id_finding"])

    def test_07_multi_row_per_accident_pattern(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.csv"; write_csv(path, [self.row("1"), self.row("2")])
            entity = audit_accident_csv(path)["accident_entity_audit"]
            self.assertEqual(entity["heuristic_groups_with_multiple_records"], 1)

    def test_08_incompatible_yearly_schema(self):
        a = {"header": ["a", "b"]}; b = {"header": ["a", "c"]}
        self.assertFalse(schema_compatibility(a, b)["safe_to_blindly_stack"])

    def test_09_confirmed_crs_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "road"; make_shapefile(directory)
            self.assertEqual(audit_road_layer(directory)["crs"]["epsg"], 3826)

    def test_10_missing_shapefile_component(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "road"; make_shapefile(directory); (directory / "Road.shx").unlink()
            with self.assertRaises(AuditError): audit_road_layer(directory)

    def test_11_duplicate_road_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "road"; make_shapefile(directory, ("R1", "R1"))
            self.assertFalse(audit_road_layer(directory)["road_id"]["unique_and_non_null"])

    def test_12_invalid_geometry(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "road"; make_shapefile(directory, invalid_geometry=True)
            self.assertEqual(audit_road_layer(directory)["shapefile"]["structurally_invalid_geometry_count"], 1)

    def test_13_deterministic_audit_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.csv"; write_csv(path, [self.row()])
            first = audit_accident_csv(path); second = audit_accident_csv(path)
            self.assertEqual(hashlib.sha256(json.dumps(first, sort_keys=True).encode()).hexdigest(), hashlib.sha256(json.dumps(second, sort_keys=True).encode()).hexdigest())
            self.assertEqual(stable_receipt_fingerprint({"generated_at_utc": "a", "x": first}), stable_receipt_fingerprint({"generated_at_utc": "b", "x": second}))


if __name__ == "__main__":
    unittest.main()
