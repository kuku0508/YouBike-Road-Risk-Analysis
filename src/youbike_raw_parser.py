"""Fail-closed parser boundary for historical Taipei YouBike monthly raw CSVs."""
from __future__ import annotations

import base64
import csv
from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import io
from pathlib import Path
import re
from typing import BinaryIO, Iterator
import zipfile


CANONICAL_COLUMNS = (
    "borrow_time",
    "origin_station_raw",
    "return_time",
    "destination_station_raw",
    "duration_raw",
    "bike_type",
    "borrow_date",
)

PROVENANCE_COLUMNS = (
    "_source_file",
    "_source_row",
    "_schema_version",
    "_parse_warnings",
)

HEADER_V1 = ("rent_time", "rent_station", "return_time", "return_station", "rent", "infodate")
HEADER_V2 = ("rent_time", "rent_station", "return_time", "return_station", "rent", "bike_type", "infodate")
KNOWN_HEADERS = {HEADER_V1: "v1_6col", HEADER_V2: "v2_7col"}
KNOWN_HEADER_TOKENS = frozenset(HEADER_V1) | frozenset(HEADER_V2)
OBSERVED_BIKE_TYPES = frozenset(("一般車", "電輔車"))

TIME_RE = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:[0-5]\d:[0-5]\d\Z")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
DURATION_RE = re.compile(r"\d+:[0-5]\d:[0-5]\d\Z")


class RawParserError(ValueError):
    """Base class for a raw file that cannot safely cross the parser boundary."""


class SchemaDetectionError(RawParserError):
    pass


class SchemaValidationError(RawParserError):
    pass


class UnsafeForSerializationError(RawParserError):
    pass


@dataclass(frozen=True)
class SchemaSpec:
    version: str
    width: int
    header: tuple[str, ...]


SCHEMAS = {
    "v1_6col": SchemaSpec("v1_6col", 6, HEADER_V1),
    "v2_7col": SchemaSpec("v2_7col", 7, HEADER_V2),
}


def _headerish(row: list[str]) -> bool:
    token_matches = sum(value in KNOWN_HEADER_TOKENS for value in row)
    return token_matches >= 2 or any("rent_" in value or value in ("rent", "infodate", "bike_type") for value in row)


def _validate_row(row: list[str], spec: SchemaSpec, source_row: int) -> None:
    if len(row) != spec.width:
        raise SchemaValidationError(
            f"row {source_row}: expected {spec.width} fields for {spec.version}, got {len(row)}"
        )
    date_index = 5 if spec.width == 6 else 6
    checks = (
        (TIME_RE, row[0], "borrow_time"),
        (TIME_RE, row[2], "return_time"),
        (DURATION_RE, row[4], "duration_raw"),
        (DATE_RE, row[date_index], "borrow_date"),
    )
    for pattern, value, field in checks:
        if not pattern.fullmatch(value):
            raise SchemaValidationError(f"row {source_row}: invalid {field} format")
    try:
        datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
        datetime.strptime(row[2], "%Y-%m-%d %H:%M:%S")
        date.fromisoformat(row[date_index])
    except ValueError as exc:
        raise SchemaValidationError(f"row {source_row}: invalid calendar date/time value") from exc
    if spec.width == 7 and row[5] not in OBSERVED_BIKE_TYPES:
        raise SchemaValidationError(
            f"row {source_row}: unrecognised bike_type {row[5]!r}; schema expansion requires review"
        )


def detect_schema(first_row: list[str]) -> tuple[SchemaSpec, bool]:
    header = tuple(first_row)
    if header in KNOWN_HEADERS:
        return SCHEMAS[KNOWN_HEADERS[header]], True
    if _headerish(first_row):
        raise SchemaDetectionError("first record resembles a header but is not an exact known header")
    candidates = [spec for spec in SCHEMAS.values() if len(first_row) == spec.width]
    if len(candidates) != 1:
        raise SchemaDetectionError(f"unknown field count in first record: {len(first_row)}")
    spec = candidates[0]
    try:
        _validate_row(first_row, spec, 1)
    except SchemaValidationError as exc:
        raise SchemaDetectionError(f"first record does not conform to {spec.version}: {exc}") from exc
    return spec, False


def _decode_warning(value: str, field: str) -> dict | None:
    invalid = [char for char in value if 0xDC80 <= ord(char) <= 0xDCFF]
    if not invalid:
        return None
    raw = value.encode("utf-8", "surrogateescape")
    return {
        "code": "invalid_utf8_bytes",
        "field": field,
        "invalid_byte_count": len(invalid),
        "field_bytes_base64": base64.b64encode(raw).decode("ascii"),
    }


def canonicalize(row: list[str], spec: SchemaSpec, source_file: str, source_row: int) -> dict:
    if spec.width == 6:
        values = (row[0], row[1], row[2], row[3], row[4], None, row[5])
    else:
        values = tuple(row)
    warnings = []
    for field, value in zip(CANONICAL_COLUMNS, values):
        if isinstance(value, str):
            warning = _decode_warning(value, field)
            if warning:
                warnings.append(warning)
    record = dict(zip(CANONICAL_COLUMNS, values))
    record.update({"_source_file": source_file, "_source_row": source_row,
                   "_schema_version": spec.version, "_parse_warnings": warnings})
    return record


def iter_stream(binary: BinaryIO, source_file: str) -> Iterator[dict]:
    """Yield canonical-but-uncleaned records from a binary CSV stream.

    The consumer must treat the destination as transactional: no staged output is
    accepted until this iterator reaches EOF without raising RawParserError.
    """
    text = io.TextIOWrapper(binary, encoding="utf-8-sig", errors="surrogateescape", newline="")
    reader = csv.reader(text, strict=True)
    try:
        first = next(reader)
    except StopIteration as exc:
        raise SchemaDetectionError("empty CSV") from exc
    except csv.Error as exc:
        raise SchemaDetectionError(f"invalid first CSV record: {exc}") from exc
    spec, has_header = detect_schema(first)
    if not has_header:
        yield canonicalize(first, spec, source_file, 1)
    try:
        for source_row, row in enumerate(reader, start=2):
            _validate_row(row, spec, source_row)
            yield canonicalize(row, spec, source_file, source_row)
    except csv.Error as exc:
        raise SchemaValidationError(f"CSV syntax error near physical line {reader.line_num}: {exc}") from exc


def iter_path(path: Path | str) -> Iterator[dict]:
    path = Path(path)
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            members = [info for info in archive.infolist() if not info.is_dir()]
            if len(members) != 1 or not members[0].filename.lower().endswith(".csv"):
                raise SchemaDetectionError("ZIP must contain exactly one CSV member")
            with archive.open(members[0]) as binary:
                yield from iter_stream(binary, f"{path.name}::{members[0].filename}")
    elif path.suffix.lower() == ".csv":
        with path.open("rb") as binary:
            yield from iter_stream(binary, path.name)
    else:
        raise SchemaDetectionError("source must be a .csv or .zip file")


def parse_bytes(payload: bytes, source_file: str = "fixture.csv") -> list[dict]:
    """Small-fixture convenience API; production callers should stream iter_path."""
    return list(iter_stream(io.BytesIO(payload), source_file))


def source_sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_serialization_safe(record: dict) -> None:
    """Block pandas/PyArrow/Parquet handoff while undecodable bytes remain."""
    if record.get("_parse_warnings"):
        raise UnsafeForSerializationError(
            "record contains losslessly preserved surrogate bytes; quarantine or resolve before UTF-8 serialization"
        )
