"""Build read-only station-name forensic evidence from the Phase 3 aggregation."""
from __future__ import annotations

import argparse
import base64
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import re
import sqlite3


ISSUES = ("illegal_utf8", "native_replacement", "question_mark", "unbalanced_parentheses")
ALLOWED_STATUSES = {"unique_supported", "ambiguous", "unresolved", "not_an_error"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def decode_station(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="surrogateescape")
    return str(value)


def raw_bytes(value: str) -> bytes:
    return value.encode("utf-8", errors="surrogateescape")


def display(value: str) -> str:
    return "".join(f"\\x{ord(ch) - 0xDC00:02x}" if 0xDC80 <= ord(ch) <= 0xDCFF else ch for ch in value)


def issue_types(value: str) -> set[str]:
    found: set[str] = set()
    if any(0xDC80 <= ord(ch) <= 0xDCFF for ch in value):
        found.add("illegal_utf8")
    if "\ufffd" in value:
        found.add("native_replacement")
    if "?" in value:
        found.add("question_mark")
    if value.count("(") != value.count(")"):
        found.add("unbalanced_parentheses")
    return found


def load_metadata(taipei_current: Path, taipei_historical: Path, new_taipei: Path):
    sources: list[dict] = []
    current = json.loads(taipei_current.read_text(encoding="utf-8-sig"))
    for row in current:
        sources.append({"name": re.sub(r"^YouBike2\.0_", "", row.get("sna", "")),
                        "id": str(row.get("sno", "")), "city": "Taipei",
                        "source": "taipei_current_2026-09-13"})
    with taipei_historical.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            sources.append({"name": row.get("Station", ""), "id": row.get("Station Number", ""),
                            "city": "Taipei", "source": "taipei_historical_2024-05-31"})
    with new_taipei.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            sources.append({"name": re.sub(r"^YouBike2\.0_", "", row.get("sna", "")),
                            "id": row.get("sno", ""), "city": "New Taipei",
                            "source": "new_taipei_current_2026-09-14"})
    return [row for row in sources if row["name"]]


def candidate_rows(value: str, issue: str, metadata: list[dict]) -> list[dict]:
    if issue == "destination_only":
        return [row for row in metadata if row["name"] == value]
    if issue == "unbalanced_parentheses":
        return [row for row in metadata if row["name"].startswith(value) or value.startswith(row["name"])]
    # Replacement markers stand for an unknown span.  This is candidate generation,
    # never a decoding or repair operation.
    pieces, current = [], []
    for ch in value:
        marker = ch in {"?", "\ufffd"} or 0xDC80 <= ord(ch) <= 0xDCFF
        if marker:
            if current:
                pieces.append(re.escape("".join(current)))
                current = []
            if not pieces or pieces[-1] != ".+?":
                pieces.append(".+?")
        else:
            current.append(ch)
    if current:
        pieces.append(re.escape("".join(current)))
    pattern = re.compile("^" + "".join(pieces) + "$")
    return [row for row in metadata if pattern.fullmatch(row["name"])]


def choose_mapping(candidates: list[dict]):
    pairs = {(r["name"], r["id"], r["city"]) for r in candidates}
    if len(pairs) == 1:
        name, station_id, city = next(iter(pairs))
        sources = sorted({r["source"] for r in candidates})
        return "unique_supported", name, station_id, city, "B", sources
    if pairs:
        return "ambiguous", " | ".join(sorted({r["name"] for r in candidates})), "", "", "C", sorted({r["source"] for r in candidates})
    return "unresolved", "", "", "", "", []


def aggregate(db_path: Path):
    stations = defaultdict(lambda: {"origin": 0, "destination": 0, "records": 0,
                                    "origin_month": Counter(), "destination_month": Counter(),
                                    "months": set(), "issues": set()})
    con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    columns = [row[1] for row in con.execute("pragma table_info(od_profile)")]
    if columns != ["origin", "destination", "month", "mask", "n"]:
        raise RuntimeError(f"unexpected od_profile schema: {columns}")
    for month, origin_raw, destination_raw, _mask, count in con.execute(
            "select month, origin, destination, mask, n from od_profile"):
        origin, destination, count = decode_station(origin_raw), decode_station(destination_raw), int(count)
        for value, side in ((origin, "origin"), (destination, "destination")):
            item = stations[value]
            item[side] += count
            item[f"{side}_month"][month] += count
            item["months"].add(month)
            item["issues"].update(issue_types(value))
        stations[origin]["records"] += count
        if destination != origin:
            stations[destination]["records"] += count
    con.close()
    return stations


def period_destination_only(stations, end_month):
    result = set()
    for value, stats in stations.items():
        origins = sum(n for month, n in stats["origin_month"].items() if month <= end_month)
        destinations = sum(n for month, n in stats["destination_month"].items() if month <= end_month)
        if value and destinations and not origins:
            result.add(value)
    return result


def record_status_assessment(db_path, rows, stations, end_month):
    rank = {"unique_supported": 0, "not_an_error": 0, "ambiguous": 1, "unresolved": 2}
    lookup = {(row["issue_type"], base64.b64decode(row["raw_value_base64"])): row["mapping_status"] for row in rows}
    dest_only = period_destination_only(stations, end_month)
    station_issues = {value: stats["issues"] for value, stats in stations.items()}
    counts = {issue: Counter() for issue in (*ISSUES, "destination_only", "any_station_anomaly")}
    con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    for month, origin_raw, destination_raw, _mask, count in con.execute(
            "select month, origin, destination, mask, n from od_profile where month<=?", (end_month,)):
        origin, destination, count = decode_station(origin_raw), decode_station(destination_raw), int(count)
        for issue in ISSUES:
            values = {v for v in (origin, destination) if issue in station_issues[v]}
            if values:
                statuses = [lookup[(issue, raw_bytes(v))] for v in values]
                counts[issue][max(statuses, key=lambda status: rank[status])] += count
        all_statuses = []
        for value in {origin, destination}:
            for issue in station_issues[value]:
                all_statuses.append(lookup[(issue, raw_bytes(value))])
        if all_statuses:
            counts["any_station_anomaly"][max(all_statuses, key=lambda status: rank[status])] += count
        if destination in dest_only:
            counts["destination_only"][lookup[("destination_only", raw_bytes(destination))]] += count
    con.close()
    return {issue: {"classified_records": sum(counter.values()), "by_status": dict(counter)}
            for issue, counter in counts.items()}


def make_row(value, issue, stats, metadata):
    candidates = candidate_rows(value, issue, metadata)
    status, candidate, station_id, city, level, sources = choose_mapping(candidates)
    if issue == "destination_only" and status == "unique_supported":
        status = "not_an_error"
    assert status in ALLOWED_STATUSES
    data = raw_bytes(value)
    notes = "candidate only; no record mutation"
    if issue == "illegal_utf8":
        notes += "; original bytes fail strict UTF-8; external evidence required"
    return {
        "raw_station_value": display(value), "raw_value_base64": base64.b64encode(data).decode("ascii"),
        "issue_type": issue, "affected_records": stats["records"],
        "first_seen": min(stats["months"]), "last_seen": max(stats["months"]),
        "months": "|".join(sorted(stats["months"])), "origin_count": stats["origin"],
        "destination_count": stats["destination"], "candidate_station_name": candidate,
        "candidate_station_id": station_id, "candidate_city": city,
        "evidence_level": level, "evidence_sources": "|".join(sources),
        "mapping_status": status, "notes": notes,
    }


def summarize(rows):
    output = {}
    for issue in (*ISSUES, "destination_only"):
        subset = [row for row in rows if row["issue_type"] == issue]
        output[issue] = {
            "unique_values": len(subset),
            "value_involvement_records": sum(int(row["affected_records"]) for row in subset),
            "status_unique_values": dict(Counter(row["mapping_status"] for row in subset)),
            "origin_occurrences": sum(int(row["origin_count"]) for row in subset),
            "destination_occurrences": sum(int(row["destination_count"]) for row in subset),
            "note": "Value-involvement counts can overlap when both station fields in one record are affected. Phase 3 record-union counts remain authoritative.",
        }
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--phase3", type=Path, required=True)
    parser.add_argument("--taipei-current", type=Path, required=True)
    parser.add_argument("--taipei-historical", type=Path, required=True)
    parser.add_argument("--new-taipei", type=Path, required=True)
    parser.add_argument("--csv-output", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    args = parser.parse_args()
    before_phase3 = sha256(args.phase3)
    metadata = load_metadata(args.taipei_current, args.taipei_historical, args.new_taipei)
    stations = aggregate(args.database)
    rows = []
    extended_destination_only = period_destination_only(stations, "2025-03")
    core_destination_only = period_destination_only(stations, "2024-12")
    for value, stats in stations.items():
        for issue in sorted(stats["issues"]):
            rows.append(make_row(value, issue, stats, metadata))
        if value in extended_destination_only or value in core_destination_only:
            rows.append(make_row(value, "destination_only", stats, metadata))
    rows.sort(key=lambda row: (row["issue_type"], row["raw_station_value"]))
    args.csv_output.parent.mkdir(parents=True, exist_ok=True)
    with args.csv_output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    phase3 = json.loads(args.phase3.read_text(encoding="utf-8"))
    evidence = {
        "phase": "3.1", "period": ["2023-01", "2025-03"],
        "method": "Read-only scan of Phase 3 od_profile unique OD/month aggregates; metadata matching creates candidates only.",
        "phase3_evidence_sha256_before": before_phase3,
        "phase3_evidence_sha256_after": sha256(args.phase3),
        "source_files": {
            "phase3": {"path": str(args.phase3), "sha256": before_phase3},
            "taipei_current": {"path": str(args.taipei_current), "sha256": sha256(args.taipei_current), "snapshot_date": "2026-09-13", "url": "https://tcgbusfs.blob.core.windows.net/dotapp/youbike/v2/youbike_immediate.json", "authority": "official"},
            "taipei_historical": {"path": str(args.taipei_historical), "sha256": sha256(args.taipei_historical), "snapshot_date": "2024-05-31", "url": "https://github.com/LittleFish-Coder/youbike-info-collector/blob/master/result/2024-05-31.csv", "authority": "third-party capture of official feed"},
            "new_taipei_current": {"path": str(args.new_taipei), "sha256": sha256(args.new_taipei), "snapshot_date": "2026-09-14", "url": "https://data.ntpc.gov.tw/api/datasets/010e5b15-3823-4b20-b401-b1cf000550c5/csv?page=0&size=5000", "authority": "official"},
        },
        "metadata_rows": dict(Counter(row["source"] for row in metadata)),
        "summary": summarize(rows),
        "record_status_assessment": {
            "core_period": record_status_assessment(args.database, rows, stations, "2024-12"),
            "extended_report_period": record_status_assessment(args.database, rows, stations, "2025-03"),
        },
        "candidate_table": str(args.csv_output),
        "interpretation_limits": [
            "A current snapshot cannot prove a station existed during every historical month.",
            "A fuzzy/prefix/wildcard match is candidate generation, not proof.",
            "No station strings or trip records were changed.",
            "Destination-only means absent from observed origins in this report period, not invalid.",
        ],
    }
    args.json_output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    if before_phase3 != sha256(args.phase3):
        raise RuntimeError("Phase 3 evidence changed")
    print(json.dumps({"rows": len(rows), "summary": evidence["summary"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
