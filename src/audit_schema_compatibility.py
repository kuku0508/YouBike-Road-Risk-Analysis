"""Download selected monthly ZIPs without overwrite and audit CSV schema read-only."""
import argparse
import base64
import codecs
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
from urllib.parse import quote
from urllib.request import urlopen
import zipfile

from audit_youbike import fingerprint, inspect_index, save


TIME_RE = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\Z")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
DURATION_RE = re.compile(r"\d+:[0-5]\d:[0-5]\d\Z")


def download_month(index, month, raw_dir):
    matches = [row for row in index["rows"] if row["month"] == month]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one source URL for {month}")
    row = matches[0]
    target = Path(raw_dir) / Path(row["fileURL"]).name
    if target.exists():
        return {**fingerprint(target), "month": month, "status": "reused_existing_raw",
                "url": row["fileURL"]}
    target.parent.mkdir(parents=True, exist_ok=True)
    md5 = hashlib.md5()
    with urlopen(quote(row["fileURL"], safe=":/"), timeout=120) as response, target.open("xb") as out:
        headers = dict(response.headers)
        for chunk in iter(lambda: response.read(1024 * 1024), b""):
            out.write(chunk)
            md5.update(chunk)
    if headers.get("Content-Length"):
        assert target.stat().st_size == int(headers["Content-Length"])
    if headers.get("Content-MD5"):
        assert base64.b64encode(md5.digest()).decode() == headers["Content-MD5"]
    return {**fingerprint(target), "month": month, "status": "downloaded",
            "url": row["fileURL"], "retrieved_utc": datetime.now(timezone.utc).isoformat(),
            "headers": headers}


def detect_encoding(zf, info):
    with zf.open(info) as member:
        sample = member.read(1024 * 1024)
    for encoding in ("utf-8-sig", "cp950"):
        try:
            # The fixed-size sample may end in the middle of a multibyte character.
            # Incremental decoding with final=False distinguishes that boundary from
            # an actually invalid byte sequence.
            codecs.getincrementaldecoder(encoding)(errors="strict").decode(sample, final=False)
            return encoding, "strict"
        except UnicodeDecodeError:
            pass
    # Preserve undecodable bytes one-to-one instead of silently replacing them.
    # Later structural checks decide whether this is otherwise valid UTF-8 CSV.
    return "utf-8-sig", "surrogateescape"


def json_safe(value):
    if isinstance(value, str) and any(0xDC80 <= ord(char) <= 0xDCFF for char in value):
        return value.encode("utf-8", "backslashreplace").decode("utf-8")
    return value


def row_conforms(row):
    if len(row) == 6:
        return bool(TIME_RE.fullmatch(row[0]) and TIME_RE.fullmatch(row[2]) and
                    DURATION_RE.fullmatch(row[4]) and DATE_RE.fullmatch(row[5]))
    if len(row) == 7:
        return bool(TIME_RE.fullmatch(row[0]) and TIME_RE.fullmatch(row[2]) and
                    DURATION_RE.fullmatch(row[4]) and DATE_RE.fullmatch(row[6]))
    return False


def infer_schema(width):
    if width == 6:
        return ["borrow_time", "origin_station_name", "return_time",
                "destination_station_name", "duration", "borrow_date"]
    if width == 7:
        return ["borrow_time", "origin_station_name", "return_time",
                "destination_station_name", "duration", "vehicle_type", "borrow_date"]
    return None


def inspect_month(zip_path, month, sample_rows=5):
    before = fingerprint(zip_path)
    widths, sixth_values = Counter(), Counter()
    rows = 0
    first_rows = []
    format_failures = Counter()
    undecodable_byte_count = 0
    members = []
    with zipfile.ZipFile(zip_path) as zf:
        infos = [info for info in zf.infolist() if not info.is_dir()]
        if not infos or any(not info.filename.lower().endswith(".csv") for info in infos):
            raise ValueError(f"{month}: expected CSV-only ZIP")
        encodings = []
        for info in infos:
            encoding, errors = detect_encoding(zf, info)
            encodings.append(f"{encoding}:{errors}")
            members.append({"zip_filename": info.filename, "bytes": info.file_size,
                            "crc32": f"{info.CRC:08x}", "encoding": encoding,
                            "decode_errors": errors})
            with zf.open(info) as raw, io.TextIOWrapper(
                    raw, encoding=encoding, errors=errors, newline="") as text:
                for row in csv.reader(text, strict=True):
                    rows += 1
                    undecodable_byte_count += sum(
                        0xDC80 <= ord(char) <= 0xDCFF for value in row for char in value)
                    widths[len(row)] += 1
                    if len(first_rows) < sample_rows:
                        first_rows.append([json_safe(value) for value in row])
                    if len(row) >= 6:
                        sixth_values[row[5]] += 1
                    if not row_conforms(row):
                        format_failures[len(row)] += 1
        if len(set(encodings)) != 1:
            encoding_summary = sorted(set(encodings))
        else:
            encoding_summary = encodings[0]
    dominant_width = widths.most_common(1)[0][0] if widths else None
    header_present = bool(first_rows and not row_conforms(first_rows[0]))
    schema = infer_schema(dominant_width)
    date_position = 7 if dominant_width == 7 else 6 if dominant_width == 6 else None
    result = {**before, "month": month, "members": members, "encoding": encoding_summary,
              "row_count": rows, "width_counts": dict(widths), "dominant_width": dominant_width,
              "header_present": header_present, "first_rows": first_rows,
              "undecodable_byte_count": undecodable_byte_count,
              "inferred_semantics": schema, "format_nonconforming_rows": sum(format_failures.values()),
              "format_nonconforming_by_width": dict(format_failures),
              "sixth_field_top_values": [[json_safe(value), count]
                                          for value, count in sixth_values.most_common(20)],
              "sixth_field_looks_like_date": bool(sixth_values and all(DATE_RE.fullmatch(v) for v in sixth_values)),
              "seventh_field_exists": dominant_width == 7,
              "vehicle_type_field_exists": dominant_width == 7,
              "date_field_position": date_position,
              "time_format": "YYYY-MM-DD HH:MM:SS" if dominant_width in (6, 7) else None,
              "duration_format": "H+:MM:SS" if dominant_width in (6, 7) else None,
              "duration_unit_interpretation": "hours:minutes:seconds" if dominant_width in (6, 7) else None}
    assert fingerprint(zip_path) == before, "Raw ZIP changed during inspection"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--months", nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    index = inspect_index(args.index)
    receipts, audits = [], []
    for month in args.months:
        receipt = download_month(index, month, args.raw_dir)
        receipts.append(receipt)
        zip_path = args.raw_dir / receipt["filename"]
        audits.append(inspect_month(zip_path, month))
    save(args.output, {"months": audits})
    save(args.receipt, {"downloads": receipts})
    print(f"Schema compatibility audit saved to {args.output}")


if __name__ == "__main__":
    main()
