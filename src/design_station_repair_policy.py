"""Design a deterministic station repair allowlist without applying repairs."""
from __future__ import annotations

import argparse
import base64
from collections import Counter, defaultdict
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3

from station_name_forensics import (
    candidate_rows, decode_station, display, issue_types, load_metadata, raw_bytes,
)


REPAIR_ISSUES = {"illegal_utf8", "native_replacement", "question_mark", "unbalanced_parentheses"}
DECISIONS = {"approved_repair", "candidate_only", "ambiguous", "unresolved", "not_an_error"}
RULE_VERSION = "station-repair-policy-v2"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def month_distance(left: str, right: str) -> int:
    a, b = datetime.strptime(left, "%Y-%m"), datetime.strptime(right, "%Y-%m")
    return abs((a.year * 12 + a.month) - (b.year * 12 + b.month))


def load_station_months(db_path: Path):
    months = defaultdict(set)
    con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    for month, origin, destination in con.execute("select month,origin,destination from od_profile"):
        months[decode_station(origin)].add(month)
        months[decode_station(destination)].add(month)
    con.close()
    return months


def temporal_match(damaged_months, candidate_months):
    pairs = sorted((bad, good) for bad in damaged_months for good in candidate_months
                   if month_distance(bad, good) <= 1)
    return pairs


def classify_mapping(forensic, candidates, station_months):
    pairs = {(row["name"], row["id"], row["city"]) for row in candidates}
    if len(pairs) > 1:
        return "Tier 3", "ambiguous", [], "multiple metadata candidates", "", False, False, True
    if not pairs:
        return "Tier 3", "unresolved", [], "no metadata candidate", "", False, False, False
    candidate_name, _station_id, _city = next(iter(pairs))
    sources = {row["source"] for row in candidates}
    historical = "taipei_historical_2024-05-31" in sources
    damaged_months = forensic["months"].split("|")
    adjacent = temporal_match(damaged_months, station_months.get(candidate_name, set()))
    evidence = []
    if historical:
        evidence.append("dated Taipei feed snapshot 2024-05-31")
    if adjacent:
        evidence.append("complete raw station name observed in same/adjacent month: " +
                        "|".join(f"{bad}->{good}" for bad, good in adjacent))
    if evidence:
        subtype = "1A" if historical and adjacent else "1B" if historical else "1C"
        return ("Tier 1", "approved_repair", evidence,
                "unique metadata candidate plus temporal/historical corroboration",
                subtype, historical, bool(adjacent), False)
    return ("Tier 2", "candidate_only", [], "current metadata unique match alone is insufficient",
            "", False, False, False)


def build_allowlist(forensic_rows, metadata, station_months):
    output = []
    for forensic in forensic_rows:
        if forensic["issue_type"] not in REPAIR_ISSUES:
            continue
        raw = base64.b64decode(forensic["raw_value_base64"]).decode("utf-8", errors="surrogateescape")
        candidates = candidate_rows(raw, forensic["issue_type"], metadata)
        (tier, decision, historical, reason, subtype, has_snapshot,
         has_temporal, has_competitor) = classify_mapping(forensic, candidates, station_months)
        if candidates:
            unique = sorted({(row["name"], row["id"], row["city"]) for row in candidates})
        else:
            unique = [("", "", "")]
        for name, station_id, city in unique:
            source_names = sorted({row["source"] for row in candidates
                                   if (row["name"], row["id"], row["city"]) == (name, station_id, city)})
            output.append({
                "raw_station_value": forensic["raw_station_value"],
                "raw_value_base64": forensic["raw_value_base64"],
                "canonical_station_name": name, "canonical_station_id": station_id,
                "canonical_city": city, "issue_type": forensic["issue_type"],
                "decision": decision, "evidence_tier": tier, "tier1_subtype": subtype,
                "metadata_unique": str(len(unique) == 1).lower(),
                "has_historical_snapshot_evidence": str(has_snapshot).lower(),
                "has_temporal_raw_evidence": str(has_temporal).lower(),
                "has_competing_candidate": str(has_competitor).lower(),
                "historical_evidence": "|".join(historical),
                "current_metadata_evidence": "|".join(s for s in source_names if "current" in s),
                "first_seen": forensic["first_seen"], "last_seen": forensic["last_seen"],
                "affected_records": forensic["affected_records"],
                "decision_reason": reason, "evidence_sources": "|".join(source_names),
                "rule_version": RULE_VERSION,
            })
    return enforce_cross_issue_conflicts(output)


def enforce_cross_issue_conflicts(rows):
    grouped = defaultdict(list)
    for row in rows:
        if row["decision"] == "approved_repair":
            grouped[row["raw_value_base64"]].append(row)
    for raw_key, matches in grouped.items():
        identities = {(row["canonical_station_name"], row["canonical_station_id"], row["canonical_city"])
                      for row in matches}
        if len(identities) > 1:
            for row in matches:
                row["decision"] = "ambiguous"
                row["evidence_tier"] = "Tier 3"
                row["tier1_subtype"] = ""
                row["has_competing_candidate"] = "true"
                row["decision_reason"] = "cross-issue approved-rule identity conflict; fail closed"
    return rows


def build_universe(forensic_rows):
    output = []
    for row in forensic_rows:
        if row["issue_type"] != "destination_only":
            continue
        matched = row["mapping_status"] == "not_an_error" and row["candidate_city"] == "New Taipei"
        output.append({
            "raw_station_value": row["raw_station_value"], "raw_value_base64": row["raw_value_base64"],
            "affected_records": row["affected_records"], "first_seen": row["first_seen"],
            "last_seen": row["last_seen"], "classification": "Cross-city valid station" if matched else "Unresolved",
            "city": row["candidate_city"], "station_name": row["candidate_station_name"],
            "station_id": row["candidate_station_id"],
            "name_validity": "confirmed" if matched else "unresolved",
            "historical_operational_status": "unresolved",
            "decision": "not_an_error" if matched else "unresolved",
            "evidence_sources": row["evidence_sources"], "rule_version": RULE_VERSION,
        })
    return output


def write_csv(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def unique_mapping_summary(rows):
    keys = {(row["raw_value_base64"], row["issue_type"]): row for row in rows}
    return dict(Counter(row["decision"] for row in keys.values()))


def record_coverage(db_path, allowlist, end_month):
    rank = {"approved_repair": 0, "candidate_only": 1, "ambiguous": 2, "unresolved": 3}
    decisions = {(row["issue_type"], row["raw_value_base64"]):
                 (row["decision"], row["tier1_subtype"]) for row in allowlist}
    issue_cache = {}
    counts = {issue: Counter() for issue in (*sorted(REPAIR_ISSUES), "any_station_anomaly")}
    subtypes = {issue: Counter() for issue in (*sorted(REPAIR_ISSUES), "any_station_anomaly")}
    con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    for _month, origin_raw, destination_raw, count in con.execute(
            "select month,origin,destination,n from od_profile where month<=?", (end_month,)):
        values = {decode_station(origin_raw), decode_station(destination_raw)}
        for value in values:
            issue_cache.setdefault(value, issue_types(value))
        record_decisions = []
        for issue in REPAIR_ISSUES:
            issue_decisions = []
            for value in values:
                if issue in issue_cache[value]:
                    key = (issue, base64.b64encode(raw_bytes(value)).decode("ascii"))
                    issue_decisions.append(decisions[key])
            if issue_decisions:
                decision = max((item[0] for item in issue_decisions), key=lambda item: rank[item])
                counts[issue][decision] += int(count)
                if decision == "approved_repair":
                    for subtype in {item[1] for item in issue_decisions}:
                        subtypes[issue][subtype] += int(count)
                record_decisions.extend(issue_decisions)
        if record_decisions:
            decision = max((item[0] for item in record_decisions), key=lambda item: rank[item])
            counts["any_station_anomaly"][decision] += int(count)
            if decision == "approved_repair":
                for subtype in {item[1] for item in record_decisions}:
                    subtypes["any_station_anomaly"][subtype] += int(count)
    con.close()
    return {issue: {"classified_record_union": sum(counter.values()), "by_decision": dict(counter),
                    "approved_subtype_record_unions": dict(subtypes[issue])}
            for issue, counter in counts.items()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--forensics", type=Path, required=True)
    parser.add_argument("--forensic-evidence", type=Path, required=True)
    parser.add_argument("--phase3-evidence", type=Path, required=True)
    parser.add_argument("--taipei-current", type=Path, required=True)
    parser.add_argument("--taipei-historical", type=Path, required=True)
    parser.add_argument("--new-taipei", type=Path, required=True)
    parser.add_argument("--allowlist-output", type=Path, required=True)
    parser.add_argument("--universe-output", type=Path, required=True)
    parser.add_argument("--evidence-output", type=Path, required=True)
    args = parser.parse_args()
    immutable_before = {str(p): sha256(p) for p in (args.forensics, args.forensic_evidence, args.phase3_evidence)}
    with args.forensics.open(encoding="utf-8-sig", newline="") as stream:
        forensic_rows = list(csv.DictReader(stream))
    metadata = load_metadata(args.taipei_current, args.taipei_historical, args.new_taipei)
    station_months = load_station_months(args.database)
    allowlist = build_allowlist(forensic_rows, metadata, station_months)
    universe = build_universe(forensic_rows)
    args.allowlist_output.parent.mkdir(parents=True, exist_ok=True)
    write_csv(args.allowlist_output, allowlist)
    write_csv(args.universe_output, universe)
    by_issue = {}
    for issue in sorted(REPAIR_ISSUES):
        subset = [row for row in allowlist if row["issue_type"] == issue]
        unique = {}
        for row in subset:
            unique.setdefault(row["raw_value_base64"], row)
        by_issue[issue] = {
            "unique_raw_values": len(unique),
            "decisions": dict(Counter(row["decision"] for row in unique.values())),
            "candidate_rows": len(subset),
        }
    evidence = {
        "phase": "3.3", "rule_version": RULE_VERSION,
        "policy": {
            "tier_1": "unique metadata candidate plus at least one dated historical snapshot or complete raw name in the same/adjacent research-period month; no competitor",
            "tier_2": "unique current metadata candidate without temporal/historical corroboration",
            "tier_3": "multiple or zero candidates, or conflicting evidence",
            "not_an_error": "station-universe reclassification; never a repair",
        },
        "allowlist_unique_mapping_summary": unique_mapping_summary(allowlist),
        "tier1_subtype_mapping_counts": dict(Counter(
            row["tier1_subtype"] for row in {key: value for key, value in
                (((r["raw_value_base64"], r["issue_type"]), r) for r in allowlist)}.values()
            if row["decision"] == "approved_repair")),
        "allowlist_by_issue": by_issue,
        "record_coverage": {
            "core_period": record_coverage(args.database, allowlist, "2024-12"),
            "extended_report_period": record_coverage(args.database, allowlist, "2025-03"),
        },
        "destination_only": {
            "unique_values": len(universe),
            "decisions": dict(Counter(row["decision"] for row in universe)),
            "value_involvement_records": dict(Counter({decision: sum(int(row["affected_records"]) for row in universe if row["decision"] == decision)
                                                        for decision in {row["decision"] for row in universe}})),
            "historical_operational_status": dict(Counter(row["historical_operational_status"] for row in universe)),
        },
        "immutability": {"before": immutable_before,
                         "after": {str(p): sha256(p) for p in (args.forensics, args.forensic_evidence, args.phase3_evidence)}},
        "outputs": {"allowlist": str(args.allowlist_output), "station_universe": str(args.universe_output)},
        "limits": ["No mapping was applied to records.", "Current metadata alone never produces Tier 1.",
                   "Value-involvement counts can overlap; Phase 3.1 record unions remain authoritative."],
    }
    args.evidence_output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    if evidence["immutability"]["before"] != evidence["immutability"]["after"]:
        raise RuntimeError("historical evidence changed")
    print(json.dumps({"mapping_summary": evidence["allowlist_unique_mapping_summary"],
                      "by_issue": by_issue, "destination_only": evidence["destination_only"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
