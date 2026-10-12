"""Attach an extended report-period profile without replacing the Phase 3 core profile."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


GLOBAL_PERIOD_ISSUES = {"destination_only_station", "rare_od_pair"}


def raw_values(profile: dict, group: str, key: str) -> set[str]:
    if group == "encoding":
        values = profile["encoding"]["unique_affected_raw_values"].get(key, [])
    else:
        values = profile["station"]["pattern_unique_values"].get(key, [])
    return {item["base64"] for item in values}


def build_comparison(core: dict, extended: dict) -> dict:
    core_months = set(core["scope"]["months"])
    added_months = [month for month in extended["scope"]["months"] if month not in core_months]
    added_total = sum(extended["monthly"][month]["total_records"] for month in added_months)
    files = {item["month"]: item for item in extended["files"]}
    core_bikes = set(core["bike_type"]["v2"])
    extended_bikes = set(extended["bike_type"]["v2"])
    pattern_keys = ("question_mark", "replacement_character", "unbalanced_parentheses", "numeric_suffix")
    station_new_values = {
        key: sorted(raw_values(extended, "station", key) - raw_values(core, "station", key))
        for key in pattern_keys
    }
    encoding_fields = sorted(extended["encoding"]["by_field"])
    new_encoding_values = {
        field: sorted(raw_values(extended, "encoding", field) - raw_values(core, "encoding", field))
        for field in encoding_fields
    }
    added_issue_counts = {
        issue: sum(extended["monthly"][month]["issue_counts"].get(issue, 0) for month in added_months)
        for issue in extended["issue_counts"]
    }
    return {
        "core_profile_semantic_sha256": core["_source_semantic_sha256"],
        "added_months": added_months,
        "added_records": added_total,
        "added_month_profiles": {month: extended["monthly"][month] for month in added_months},
        "schema": {
            "observed": {
                month: {"schema_version": files[month]["schema_version"], "header_present": files[month]["header_present"]}
                for month in added_months
            },
            "new_behavior_observed": any(
                files[month]["schema_version"] != "v2_7col" or files[month]["header_present"]
                for month in added_months
            ),
        },
        "bike_type": {
            "new_values": sorted(extended_bikes - core_bikes),
            "added_counts": {
                key: extended["bike_type"]["v2"].get(key, 0) - core["bike_type"]["v2"].get(key, 0)
                for key in sorted(extended_bikes | core_bikes)
            },
        },
        "encoding": {
            "added_illegal_bytes": extended["encoding"]["illegal_byte_count"] - core["encoding"]["illegal_byte_count"],
            "added_affected_fields": extended["encoding"]["affected_field_count"] - core["encoding"]["affected_field_count"],
            "added_affected_records": extended["encoding"]["affected_record_count"] - core["encoding"]["affected_record_count"],
            "new_affected_fields": sorted(set(extended["encoding"]["by_field"]) - set(core["encoding"]["by_field"])),
            "new_raw_values_base64": new_encoding_values,
        },
        "station_patterns": {
            "new_pattern_classes": [],
            "new_raw_values_base64": station_new_values,
            "added_issue_counts": {
                issue: added_issue_counts[issue]
                for issue in ("station_question_mark", "station_replacement_character", "station_unbalanced_parentheses")
            },
        },
        "duration_temporal": {
            "added_issue_counts": {
                issue: added_issue_counts[issue]
                for issue in ("duration_zero", "duration_gt_24h", "duration_gt_7d", "return_before_borrow", "duration_timestamp_delta_ge_1h")
            },
            "added_cross_midnight_candidates": sum(
                extended["monthly"][month]["temporal"].get("cross_midnight_candidate", 0) for month in added_months
            ),
            "added_same_timestamp": sum(
                extended["monthly"][month]["temporal"].get("same_timestamp", 0) for month in added_months
            ),
            "core_quantiles_seconds": core["duration_seconds"]["quantiles"],
            "extended_quantiles_seconds": extended["duration_seconds"]["quantiles"],
        },
        "period_global_note": (
            "destination_only_station and rare_od_pair are recomputed over each period; "
            "extended unions are not core unions plus added-month unions"
        ),
        "period_global_issue_deltas": {
            issue: extended["issue_counts"][issue]["count"] - core["issue_counts"][issue]["count"]
            for issue in GLOBAL_PERIOD_ISSUES
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", type=Path, default=Path("notes/data-quality-profile.json"))
    parser.add_argument("--extended", type=Path, default=Path("data/interim/phase3-extended-profile.json"))
    parser.add_argument("--output", type=Path, default=Path("notes/data-quality-profile.json"))
    args = parser.parse_args()
    core = json.loads(args.core.read_text(encoding="utf-8"))
    if "extended_report_period" in core:
        core.pop("extended_report_period")
        core.pop("extension_comparison", None)
        core.pop("period_layout", None)
        core.pop("_source_semantic_sha256", None)
    canonical_core = json.dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    core["_source_semantic_sha256"] = hashlib.sha256(canonical_core).hexdigest()
    extended = json.loads(args.extended.read_text(encoding="utf-8"))
    comparison = build_comparison(core, extended)
    core.pop("_source_semantic_sha256")
    core["period_layout"] = {
        "root_profile": "core_period_2023-01_to_2024-12",
        "extended_profile_key": "extended_report_period",
        "core_denominator_preserved": True,
    }
    core["extended_report_period"] = extended
    core["extension_comparison"] = comparison
    args.output.write_text(json.dumps(core, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"WROTE {args.output}; core denominator={core['total_records']}; extended denominator={extended['total_records']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
