"""Read-only Phase 3 profiler for Taipei YouBike monthly raw archives.

The profiler never emits cleaned records.  It decodes with surrogateescape,
applies the Phase 2.6 structural contract, and aggregates issue evidence only.
"""
from __future__ import annotations

import argparse
import base64
import csv
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import io
import itertools
import json
from pathlib import Path
import re
import sqlite3
import struct
import sys
from urllib.request import Request, urlopen
from urllib.parse import quote
import zipfile

from youbike_raw_parser import (
    DATE_RE,
    DURATION_RE,
    HEADER_V1,
    HEADER_V2,
    OBSERVED_BIKE_TYPES,
    TIME_RE,
    detect_schema,
)

CORE_MONTHS = tuple(f"{year}-{month:02d}" for year in (2023, 2024) for month in range(1, 13))
EXTENDED_REPORT_MONTHS = CORE_MONTHS + ("2025-01", "2025-02", "2025-03")
POSITIONAL_COLUMNS = {
    "v1_6col": ("borrow_time", "origin_station_raw", "return_time", "destination_station_raw", "duration_raw", "borrow_date"),
    "v2_7col": ("borrow_time", "origin_station_raw", "return_time", "destination_station_raw", "duration_raw", "bike_type", "borrow_date"),
}
ISSUE_CATEGORY = {
    "invalid_file_schema": "Invalid",
    "invalid_field_count": "Invalid",
    "invalid_borrow_time": "Invalid",
    "invalid_return_time": "Invalid",
    "invalid_duration": "Invalid",
    "invalid_borrow_date": "Invalid",
    "unsupported_bike_type": "Invalid",
    "origin_missing": "Quality issue",
    "destination_missing": "Quality issue",
    "illegal_utf8": "Quality issue",
    "station_replacement_character": "Quality issue",
    "station_question_mark": "Quality issue",
    "station_unbalanced_parentheses": "Quality issue",
    "duration_zero": "Suspicious",
    "duration_gt_24h": "Suspicious",
    "duration_gt_7d": "Suspicious",
    "return_before_borrow": "Suspicious",
    "duration_timestamp_delta_ge_1h": "Suspicious",
    "destination_only_station": "Suspicious",
    "rare_od_pair": "Suspicious",
}
ISSUES = tuple(ISSUE_CATEGORY)
ISSUE_BITS = {name: 1 << i for i, name in enumerate(ISSUES)}
CATEGORY_BITS = {
    name: sum(ISSUE_BITS[i] for i, category in ISSUE_CATEGORY.items() if category == name)
    for name in ("Invalid", "Quality issue", "Suspicious")
}
SUFFIX_RE = re.compile(r"_\d+\Z")
CHUNK_SIZE = 100_000


def parse_duration(value: str) -> int:
    hours, minutes, seconds = (int(part) for part in value.split(":"))
    return hours * 3600 + minutes * 60 + seconds


def byte_key(fields: list[str] | tuple[str, ...]) -> bytes:
    chunks = []
    for value in fields:
        raw = value.encode("utf-8", errors="surrogateescape")
        chunks.append(struct.pack(">I", len(raw)))
        chunks.append(raw)
    return b"".join(chunks)


def display_raw(value: str) -> dict[str, str]:
    raw = value.encode("utf-8", errors="surrogateescape")
    return {
        "escaped": value.encode("unicode_escape", errors="backslashreplace").decode("ascii"),
        "base64": base64.b64encode(raw).decode("ascii"),
    }


def illegal_byte_count(value: str) -> int:
    return sum(0xDC80 <= ord(char) <= 0xDCFF for char in value)


def unbalanced_parentheses(value: str) -> bool:
    return value.count("(") != value.count(")") or value.count("（") != value.count("）")


def validate_value(pattern, parser, value: str) -> bool:
    if not pattern.fullmatch(value):
        return False
    try:
        parser(value)
        return True
    except ValueError:
        return False


def invalid_issues(row: list[str], schema: str) -> set[str]:
    expected = 6 if schema == "v1_6col" else 7
    if len(row) != expected:
        return {"invalid_field_count"}
    issues: set[str] = set()
    if not validate_value(TIME_RE, lambda x: datetime.strptime(x, "%Y-%m-%d %H:%M:%S"), row[0]):
        issues.add("invalid_borrow_time")
    if not validate_value(TIME_RE, lambda x: datetime.strptime(x, "%Y-%m-%d %H:%M:%S"), row[2]):
        issues.add("invalid_return_time")
    if not DURATION_RE.fullmatch(row[4]):
        issues.add("invalid_duration")
    date_index = 5 if schema == "v1_6col" else 6
    if not validate_value(DATE_RE, lambda x: datetime.strptime(x, "%Y-%m-%d"), row[date_index]):
        issues.add("invalid_borrow_date")
    if schema == "v2_7col" and row[5] not in OBSERVED_BIKE_TYPES:
        issues.add("unsupported_bike_type")
    return issues


def read_source_index(path: Path) -> dict[str, str]:
    with path.open("r", encoding="cp950", newline="") as handle:
        rows = list(csv.DictReader(handle))
    urls: dict[str, str] = {}
    for row in rows:
        fileinfo = str(row.get("fileinfo", "")).strip()
        url = str(row.get("fileURL", "")).strip()
        if fileinfo and url:
            urls[datetime.strptime(fileinfo, "%Y/%m/%d").strftime("%Y-%m")] = url
    return urls


def archive_path(raw_dir: Path, month: str) -> Path:
    return raw_dir / f"{month.replace('-', '')}_YouBike2.0票證刷卡資料.zip"


def download_archive(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".part")
    request = Request(quote(url, safe=":/"), headers={"User-Agent": "YouBike-phase3-profiler/1.0"})
    with urlopen(request, timeout=180) as response, temporary.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
    if not zipfile.is_zipfile(temporary):
        temporary.unlink(missing_ok=True)
        raise ValueError(f"downloaded payload is not a ZIP archive: {url}")
    temporary.replace(target)


def archive_csv_member(archive: Path) -> str:
    with zipfile.ZipFile(archive) as zf:
        members = [item.filename for item in zf.infolist() if not item.is_dir() and item.filename.lower().endswith(".csv")]
    if len(members) != 1:
        raise ValueError(f"expected exactly one CSV member in {archive}, found {len(members)}")
    return members[0]


def open_csv_rows(archive: Path, member: str):
    zf = zipfile.ZipFile(archive)
    raw = zf.open(member, "r")
    text = io.TextIOWrapper(raw, encoding="utf-8", errors="surrogateescape", newline="")
    return zf, text, csv.reader(text)


def flush_counter(connection: sqlite3.Connection, table: str, columns: tuple[str, ...], values: Counter) -> None:
    if not values:
        return
    placeholders = ",".join("?" for _ in range(len(columns) + 1))
    names = ",".join(columns) + ",n"
    conflict = ",".join(columns)
    statement = f"INSERT INTO {table} ({names}) VALUES ({placeholders}) ON CONFLICT({conflict}) DO UPDATE SET n=n+excluded.n"
    rows = []
    for key, count in values.items():
        key_tuple = key if isinstance(key, tuple) else (key,)
        rows.append((*key_tuple, count))
    connection.executemany(statement, rows)
    connection.commit()
    values.clear()


def add_mask(mask_counts: Counter, monthly_masks: dict[str, Counter], issue_counts: Counter,
             monthly_issues: dict[str, Counter], month: str, issues: set[str], count: int = 1) -> int:
    mask = sum(ISSUE_BITS[name] for name in issues)
    mask_counts[mask] += count
    monthly_masks[month][mask] += count
    for issue in issues:
        issue_counts[issue] += count
        monthly_issues[month][issue] += count
    return mask


def move_mask(mask_counts: Counter, monthly_masks: dict[str, Counter], issue_counts: Counter,
              monthly_issues: dict[str, Counter], month: str, old_mask: int, issue: str, count: int) -> None:
    if old_mask & ISSUE_BITS[issue]:
        return
    new_mask = old_mask | ISSUE_BITS[issue]
    mask_counts[old_mask] -= count
    mask_counts[new_mask] += count
    monthly_masks[month][old_mask] -= count
    monthly_masks[month][new_mask] += count
    issue_counts[issue] += count
    monthly_issues[month][issue] += count


def category_mask(issue_mask: int) -> int:
    value = 0
    for index, category in enumerate(("Invalid", "Quality issue", "Suspicious")):
        if issue_mask & CATEGORY_BITS[category]:
            value |= 1 << index
    return value


def quantiles_from_histogram(connection: sqlite3.Connection, total: int) -> dict[str, int | None]:
    if not total:
        return {name: None for name in ("P50", "P90", "P95", "P99", "P99.9", "max")}
    targets = [("P50", 0.5), ("P90", 0.9), ("P95", 0.95), ("P99", 0.99), ("P99.9", 0.999)]
    ranks = {name: max(1, int((total * probability) + 0.999999999)) for name, probability in targets}
    results: dict[str, int | None] = {name: None for name, _ in targets}
    cumulative = 0
    maximum = None
    for seconds, count in connection.execute("SELECT seconds,n FROM duration_counts ORDER BY seconds"):
        cumulative += count
        maximum = seconds
        for name, _ in targets:
            if results[name] is None and cumulative >= ranks[name]:
                results[name] = seconds
    results["max"] = maximum
    return results


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def profile(months: tuple[str, ...], raw_dir: Path, source_index: Path, database: Path,
            download_missing: bool = False, progress=None) -> dict:
    progress = progress or (lambda message: None)
    urls = read_source_index(source_index)
    raw_dir.mkdir(parents=True, exist_ok=True)
    database.parent.mkdir(parents=True, exist_ok=True)
    database.unlink(missing_ok=True)
    connection = sqlite3.connect(database)
    connection.executescript("""
        PRAGMA journal_mode=OFF;
        PRAGMA synchronous=OFF;
        PRAGMA temp_store=FILE;
        PRAGMA cache_size=-262144;
        CREATE TABLE exact_rows (row_key BLOB PRIMARY KEY, n INTEGER NOT NULL);
        CREATE TABLE od_profile (
            origin BLOB NOT NULL, destination BLOB NOT NULL, month TEXT NOT NULL,
            mask INTEGER NOT NULL, n INTEGER NOT NULL,
            PRIMARY KEY(origin,destination,month,mask)
        );
        CREATE TABLE duration_counts (seconds INTEGER PRIMARY KEY, n INTEGER NOT NULL);
    """)

    issue_counts: Counter = Counter()
    monthly_issues: dict[str, Counter] = defaultdict(Counter)
    mask_counts: Counter = Counter()
    monthly_masks: dict[str, Counter] = defaultdict(Counter)
    origin_names: set[bytes] = set()
    destination_profile: Counter = Counter()
    station_metrics = defaultdict(Counter)
    station_unique = defaultdict(dict)
    encoding = {
        "illegal_byte_count": 0, "affected_field_count": 0, "affected_record_count": 0,
        "origin_affected_records": 0, "destination_affected_records": 0,
        "records_with_multiple_affected_fields": 0,
        "by_month": defaultdict(Counter), "by_field": defaultdict(Counter), "unique_values": defaultdict(dict),
    }
    temporal = Counter()
    temporal_monthly = defaultdict(Counter)
    bike_type = {"v1_structural_absence": 0, "v2": Counter()}
    duration_total = 0
    od_total = 0
    files = []
    repeated_by_month = {}

    for month in months:
        archive = archive_path(raw_dir, month)
        if not archive.exists():
            if not download_missing:
                raise FileNotFoundError(f"missing {archive}; rerun with --download-missing")
            if month not in urls:
                raise KeyError(f"source index has no URL for {month}")
            progress(f"DOWNLOAD {month}")
            download_archive(urls[month], archive)
        progress(f"PROFILE {month}")
        member = archive_csv_member(archive)
        file_info = {
            "month": month, "archive": archive.name, "bytes": archive.stat().st_size,
            "sha256": sha256_file(archive), "csv_member": member,
            "schema_version": None, "header_present": None, "records": 0,
        }
        exact_chunk: Counter = Counter()
        od_chunk: Counter = Counter()
        duration_chunk: Counter = Counter()
        connection.execute("DELETE FROM exact_rows")
        connection.commit()
        zf, text, reader = open_csv_rows(archive, member)
        try:
            try:
                first = next(reader)
            except StopIteration:
                first = None
            if first is None:
                files.append(file_info)
                continue
            try:
                specification, has_header = detect_schema(first)
                schema = specification.version
                file_info["schema_version"] = schema
                file_info["header_present"] = has_header
                rows = reader if has_header else itertools.chain((first,), reader)
            except Exception:
                schema = None
                file_info["header_present"] = False
                rows = itertools.chain((first,), reader)

            for row in rows:
                file_info["records"] += 1
                exact_chunk[byte_key(row)] += 1
                issues = {"invalid_file_schema"} if schema is None else invalid_issues(row, schema)
                expected_width = 0 if schema is None else (6 if schema == "v1_6col" else 7)
                mapped = len(row) == expected_width and schema is not None
                positional = POSITIONAL_COLUMNS.get(schema, ())

                affected_fields = []
                for index, value in enumerate(row):
                    count = illegal_byte_count(value)
                    if not count:
                        continue
                    field = positional[index] if index < len(positional) else f"extra_field_{index + 1}"
                    affected_fields.append(field)
                    encoding["illegal_byte_count"] += count
                    encoding["affected_field_count"] += 1
                    encoding["by_month"][month]["illegal_byte_count"] += count
                    encoding["by_month"][month]["affected_field_count"] += 1
                    encoding["by_field"][field]["illegal_byte_count"] += count
                    encoding["by_field"][field]["affected_field_count"] += 1
                    raw_key = value.encode("utf-8", errors="surrogateescape")
                    encoding["unique_values"][field][raw_key] = display_raw(value)
                if affected_fields:
                    issues.add("illegal_utf8")
                    encoding["affected_record_count"] += 1
                    encoding["by_month"][month]["affected_record_count"] += 1
                    for field in set(affected_fields):
                        encoding["by_field"][field]["affected_record_count"] += 1
                    if "origin_station_raw" in affected_fields:
                        encoding["origin_affected_records"] += 1
                    if "destination_station_raw" in affected_fields:
                        encoding["destination_affected_records"] += 1
                    if len(set(affected_fields)) > 1:
                        encoding["records_with_multiple_affected_fields"] += 1

                if mapped:
                    origin, destination = row[1], row[3]
                    if not origin:
                        issues.add("origin_missing")
                    if not destination:
                        issues.add("destination_missing")
                    for side, value in (("origin", origin), ("destination", destination)):
                        if "�" in value:
                            issues.add("station_replacement_character")
                            station_metrics[month][f"{side}_replacement_character"] += 1
                            station_unique["replacement_character"][value.encode("utf-8", "surrogateescape")] = display_raw(value)
                        if "?" in value:
                            issues.add("station_question_mark")
                            station_metrics[month][f"{side}_question_mark"] += 1
                            station_unique["question_mark"][value.encode("utf-8", "surrogateescape")] = display_raw(value)
                        if unbalanced_parentheses(value):
                            issues.add("station_unbalanced_parentheses")
                            station_metrics[month][f"{side}_unbalanced_parentheses"] += 1
                            station_unique["unbalanced_parentheses"][value.encode("utf-8", "surrogateescape")] = display_raw(value)
                        if SUFFIX_RE.search(value):
                            station_metrics[month][f"{side}_numeric_suffix"] += 1
                            station_unique["numeric_suffix"][value.encode("utf-8", "surrogateescape")] = display_raw(value)

                    if origin:
                        origin_key = origin.encode("utf-8", "surrogateescape")
                        origin_names.add(origin_key)
                    else:
                        origin_key = b""
                    destination_key = destination.encode("utf-8", "surrogateescape") if destination else b""

                    valid_duration = "invalid_duration" not in issues
                    if valid_duration:
                        seconds = parse_duration(row[4])
                        duration_total += 1
                        duration_chunk[seconds] += 1
                        if seconds == 0:
                            issues.add("duration_zero")
                        if seconds > 24 * 3600:
                            issues.add("duration_gt_24h")
                        if seconds > 7 * 24 * 3600:
                            issues.add("duration_gt_7d")
                    valid_borrow = "invalid_borrow_time" not in issues
                    valid_return = "invalid_return_time" not in issues
                    if valid_borrow and valid_return:
                        borrow_dt = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
                        return_dt = datetime.strptime(row[2], "%Y-%m-%d %H:%M:%S")
                        if return_dt.date() > borrow_dt.date():
                            temporal["cross_midnight_candidate"] += 1
                            temporal_monthly[month]["cross_midnight_candidate"] += 1
                        if return_dt < borrow_dt:
                            issues.add("return_before_borrow")
                            temporal["return_before_borrow"] += 1
                            temporal_monthly[month]["return_before_borrow"] += 1
                        if return_dt == borrow_dt:
                            temporal["same_timestamp"] += 1
                            temporal_monthly[month]["same_timestamp"] += 1
                        if valid_duration:
                            delta = int((return_dt - borrow_dt).total_seconds())
                            if abs(delta - seconds) >= 3600:
                                issues.add("duration_timestamp_delta_ge_1h")
                                temporal["duration_timestamp_delta_ge_1h"] += 1
                                temporal_monthly[month]["duration_timestamp_delta_ge_1h"] += 1

                    if schema == "v1_6col":
                        bike_type["v1_structural_absence"] += 1
                    else:
                        value = row[5]
                        label = value if value in OBSERVED_BIKE_TYPES else ("blank_or_null" if not value else "unknown")
                        bike_type["v2"][label] += 1

                mask = add_mask(mask_counts, monthly_masks, issue_counts, monthly_issues, month, issues)
                if mapped and destination:
                    destination_profile[(month, destination_key, mask)] += 1
                if mapped and origin and destination:
                    od_chunk[(origin_key, destination_key, month, mask)] += 1
                    od_total += 1

                if file_info["records"] % CHUNK_SIZE == 0:
                    flush_counter(connection, "exact_rows", ("row_key",), exact_chunk)
                    flush_counter(connection, "od_profile", ("origin", "destination", "month", "mask"), od_chunk)
                    flush_counter(connection, "duration_counts", ("seconds",), duration_chunk)
                    progress(f"ROWS {month} {file_info['records']}")
            flush_counter(connection, "exact_rows", ("row_key",), exact_chunk)
            flush_counter(connection, "od_profile", ("origin", "destination", "month", "mask"), od_chunk)
            flush_counter(connection, "duration_counts", ("seconds",), duration_chunk)
        finally:
            text.close()
            zf.close()

        multiplicity = {"2": 0, "3": 0, "4": 0, "5_plus": 0}
        groups = records = excess = 0
        for n, group_count in connection.execute("SELECT n,COUNT(*) FROM exact_rows WHERE n>=2 GROUP BY n"):
            groups += group_count
            records += n * group_count
            excess += (n - 1) * group_count
            multiplicity[str(n) if n < 5 else "5_plus"] += group_count
        repeated_by_month[month] = {
            "repeated_groups": groups, "involved_records": records,
            "excess_copies": excess, "multiplicity_groups": multiplicity,
        }
        files.append(file_info)

    # Destination-only is global to the requested profile period, not month-local.
    destination_only_values: dict[bytes, dict[str, str]] = {}
    for (month, destination, old_mask), count in destination_profile.items():
        if destination not in origin_names:
            move_mask(mask_counts, monthly_masks, issue_counts, monthly_issues,
                      month, old_mask, "destination_only_station", count)
            destination_only_values[destination] = display_raw(destination.decode("utf-8", "surrogateescape"))

    # A rare OD pair is defined descriptively as occurring exactly once in the
    # complete requested-period profile.  It remains retained and is not an error.
    for _origin, _destination, month, old_mask, count in connection.execute("""
        SELECT origin,destination,MIN(month),MIN(mask),SUM(n)
        FROM od_profile GROUP BY origin,destination HAVING SUM(n)=1
    """):
        move_mask(mask_counts, monthly_masks, issue_counts, monthly_issues,
                  month, old_mask, "rare_od_pair", count)

    total = sum(item["records"] for item in files)
    category_combo_counts = Counter()
    for mask, count in mask_counts.items():
        if count:
            category_combo_counts[category_mask(mask)] += count
    category_union = {
        category: sum(count for combo, count in category_combo_counts.items() if combo & (1 << index))
        for index, category in enumerate(("Invalid", "Quality issue", "Suspicious"))
    }
    clean = category_combo_counts[0]

    overlap = {}
    for left_index, left in enumerate(ISSUES):
        overlap[left] = {}
        for right_index, right in enumerate(ISSUES):
            overlap[left][right] = sum(
                count for mask, count in mask_counts.items()
                if mask & (1 << left_index) and mask & (1 << right_index)
            )

    category_overlap = {}
    categories = ("Invalid", "Quality issue", "Suspicious")
    for left_i, left in enumerate(categories):
        category_overlap[left] = {}
        for right_i, right in enumerate(categories):
            category_overlap[left][right] = sum(
                count for combo, count in category_combo_counts.items()
                if combo & (1 << left_i) and combo & (1 << right_i)
            )

    monthly = {}
    for month in months:
        month_total = next(item["records"] for item in files if item["month"] == month)
        combos = Counter()
        for mask, count in monthly_masks[month].items():
            if count:
                combos[category_mask(mask)] += count
        monthly[month] = {
            "total_records": month_total,
            "issue_counts": dict(sorted(monthly_issues[month].items())),
            "invalid_union": sum(n for combo, n in combos.items() if combo & 1),
            "quality_union": sum(n for combo, n in combos.items() if combo & 2),
            "suspicious_union": sum(n for combo, n in combos.items() if combo & 4),
            "clean_with_respect_to_current_rules": combos[0],
            "encoding": dict(encoding["by_month"][month]),
            "station_patterns": dict(station_metrics[month]),
            "temporal": dict(temporal_monthly[month]),
            "repeated_identical": repeated_by_month[month],
        }

    repeated_total = {
        "repeated_groups": sum(x["repeated_groups"] for x in repeated_by_month.values()),
        "involved_records": sum(x["involved_records"] for x in repeated_by_month.values()),
        "excess_copies": sum(x["excess_copies"] for x in repeated_by_month.values()),
        "multiplicity_groups": {
            key: sum(x["multiplicity_groups"][key] for x in repeated_by_month.values())
            for key in ("2", "3", "4", "5_plus")
        },
        "policy": "retain_all",
    }
    encoding_result = {
        key: value for key, value in encoding.items() if key not in ("by_month", "by_field", "unique_values")
    }
    encoding_result["affected_records_percentage"] = (encoding["affected_record_count"] / total * 100) if total else 0
    encoding_result["by_field"] = {field: dict(counts) for field, counts in sorted(encoding["by_field"].items())}
    encoding_result["unique_affected_raw_values"] = {
        field: list(values.values()) for field, values in sorted(encoding["unique_values"].items())
    }

    result = {
        "profile_version": "phase3-v1",
        "scope": {"period": [months[0], months[-1]], "months": list(months), "denominator": "CSV data records; exact header excluded"},
        "total_records": total,
        "category_unions": {
            "invalid": {"count": category_union["Invalid"], "percentage": category_union["Invalid"] / total * 100 if total else 0},
            "quality_issue": {"count": category_union["Quality issue"], "percentage": category_union["Quality issue"] / total * 100 if total else 0},
            "suspicious": {"count": category_union["Suspicious"], "percentage": category_union["Suspicious"] / total * 100 if total else 0},
            "clean_with_respect_to_current_rules": {"count": clean, "percentage": clean / total * 100 if total else 0},
        },
        "issue_definitions": {
            name: {"category": category, "status": "investigate" if category != "Suspicious" else "retain"}
            for name, category in ISSUE_CATEGORY.items()
        },
        "issue_counts": {
            name: {"count": issue_counts[name], "percentage": issue_counts[name] / total * 100 if total else 0}
            for name in ISSUES
        },
        "category_combination_counts": {
            format(combo, "03b"): count for combo, count in sorted(category_combo_counts.items())
        },
        "category_overlap_matrix": category_overlap,
        "issue_overlap_matrix": overlap,
        "files": files,
        "monthly": monthly,
        "encoding": encoding_result,
        "station": {
            "destination_only_unique_values": len(destination_only_values),
            "destination_only_values": list(destination_only_values.values()),
            "pattern_unique_values": {key: list(values.values()) for key, values in station_unique.items()},
            "numeric_suffix_policy": "profile_only_not_error",
        },
        "duration_seconds": {
            "valid_record_count": duration_total,
            "quantiles": quantiles_from_histogram(connection, duration_total),
            "unit": "seconds",
        },
        "temporal": dict(temporal),
        "bike_type": {
            "v1_structural_absence": bike_type["v1_structural_absence"],
            "v2": dict(bike_type["v2"]),
            "v1_absence_is_quality_issue": False,
        },
        "od": {"nonblank_origin_destination_records": od_total, "rare_definition": "origin/destination raw pair occurs exactly once in the requested profile period"},
        "repeated_identical": repeated_total,
        "method": {
            "decode": "utf-8 with surrogateescape; no replacement or repair",
            "station_matching": "exact raw decoded value; no normalization or reconciliation",
            "cleaning_performed": False,
            "duplicates_removed": False,
        },
    }
    connection.close()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--source-index", type=Path, default=Path("references/臺北市公共自行車2.0租借紀錄(20260911更新_V5).csv"))
    parser.add_argument("--database", type=Path, default=Path("data/interim/phase3-profile.sqlite"))
    parser.add_argument("--output", type=Path, default=Path("notes/data-quality-profile.json"))
    parser.add_argument("--download-missing", action="store_true")
    parser.add_argument("--period", choices=("core", "extended"), default="core")
    parser.add_argument("--months", nargs="+")
    args = parser.parse_args()
    months = tuple(args.months) if args.months else (CORE_MONTHS if args.period == "core" else EXTENDED_REPORT_MONTHS)
    result = profile(months, args.raw_dir, args.source_index, args.database,
                     args.download_missing, lambda message: print(message, flush=True))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"WROTE {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
