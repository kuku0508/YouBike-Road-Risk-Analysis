"""Small, fail-closed station cleaning execution contract; no bulk I/O."""
from __future__ import annotations

import base64
import csv
from dataclasses import dataclass
from pathlib import Path


class RepairContractError(RuntimeError):
    pass


@dataclass(frozen=True)
class RepairRule:
    raw_value_base64: str
    canonical_station_name: str
    canonical_station_id: str
    canonical_city: str
    decision: str
    evidence_tier: str
    tier1_subtype: str
    evidence_sources: str
    rule_version: str


def _yes(value: str) -> bool:
    return value.strip().lower() == "true"


def load_allowlist(path: Path, expected_version: str) -> dict[str, tuple[RepairRule, ...]]:
    if not expected_version:
        raise RepairContractError("allowlist version is required")
    grouped: dict[str, list[RepairRule]] = {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if row["rule_version"] != expected_version:
                raise RepairContractError("unknown or mixed allowlist version")
            if row["decision"] == "approved_repair":
                if row["evidence_tier"] != "Tier 1" or row["tier1_subtype"] not in {"1A", "1B", "1C"}:
                    raise RepairContractError("approved rule lacks a valid Tier 1 subtype")
                if not _yes(row["metadata_unique"]) or _yes(row["has_competing_candidate"]):
                    raise RepairContractError("approved rule is not uniquely identified")
                if not (_yes(row["has_historical_snapshot_evidence"]) or _yes(row["has_temporal_raw_evidence"])):
                    raise RepairContractError("approved rule lacks temporal evidence")
                if not row["evidence_sources"] or not row["canonical_station_name"] or not row["canonical_station_id"]:
                    raise RepairContractError("approved rule lacks provenance or canonical identity")
            rule = RepairRule(row["raw_value_base64"], row["canonical_station_name"],
                              row["canonical_station_id"], row["canonical_city"], row["decision"],
                              row["evidence_tier"], row["tier1_subtype"], row["evidence_sources"],
                              row["rule_version"])
            grouped.setdefault(rule.raw_value_base64, []).append(rule)
    for raw_key, rules in grouped.items():
        approved = {(r.canonical_station_name, r.canonical_station_id, r.canonical_city)
                    for r in rules if r.decision == "approved_repair"}
        if len(approved) > 1:
            raise RepairContractError(f"conflicting approved rules for {raw_key}")
    return {key: tuple(value) for key, value in grouped.items()}


def apply_station_contract(raw_value: str, rules: dict[str, tuple[RepairRule, ...]]) -> dict[str, str]:
    raw_key = base64.b64encode(raw_value.encode("utf-8", errors="surrogateescape")).decode("ascii")
    matches = rules.get(raw_key, ())
    approved = [rule for rule in matches if rule.decision == "approved_repair"]
    if approved:
        identities = {(r.canonical_station_name, r.canonical_station_id, r.canonical_city) for r in approved}
        if len(identities) != 1:
            raise RepairContractError("runtime approved-rule conflict")
        rule = approved[0]
        return {"station_raw": raw_value, "station_clean": rule.canonical_station_name,
                "station_id": rule.canonical_station_id, "station_city": rule.canonical_city,
                "repair_status": "approved_repair", "rule_version": rule.rule_version,
                "evidence_tier": rule.evidence_tier, "tier1_subtype": rule.tier1_subtype,
                "evidence_sources": rule.evidence_sources}
    priority = {"ambiguous": 3, "unresolved": 2, "candidate_only": 1}
    status = max((r.decision for r in matches), key=lambda item: priority.get(item, 0),
                 default="unchanged_no_rule")
    return {"station_raw": raw_value, "station_clean": raw_value, "station_id": "",
            "station_city": "", "repair_status": status, "rule_version": "",
            "evidence_tier": "", "tier1_subtype": "", "evidence_sources": ""}
