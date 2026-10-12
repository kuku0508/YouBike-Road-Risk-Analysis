"""Profile current/historical station snapshots and test name-match feasibility."""
import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import re

from audit_youbike import fingerprint, save


CORE = ("station_id", "station_name", "district", "address", "latitude", "longitude")


def profile(records, source, source_url, snapshot_date):
    missing = {field: sum(not str(row.get(field, "")).strip() for row in records) for field in CORE}
    id_to_names, name_to_ids = defaultdict(set), defaultdict(set)
    for row in records:
        station_id = str(row.get("station_id", "")).strip()
        name = str(row.get("station_name", "")).strip()
        if station_id and name:
            id_to_names[station_id].add(name)
            name_to_ids[name].add(station_id)
    return {"source": source, "source_url": source_url, "snapshot_date": snapshot_date,
            "row_count": len(records), "available_fields": sorted(set().union(*(r.keys() for r in records))),
            "missing_core_fields": missing,
            "unique_station_ids": len(id_to_names), "unique_station_names": len(name_to_ids),
            "station_ids_with_multiple_names": {k: sorted(v) for k, v in id_to_names.items() if len(v) > 1},
            "station_names_with_multiple_ids": {k: sorted(v) for k, v in name_to_ids.items() if len(v) > 1},
            "has_valid_from": any("valid_from" in row for row in records),
            "has_valid_to": any("valid_to" in row for row in records)}


def load_current(path):
    raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    records = []
    for row in raw:
        records.append({"station_id": row.get("sno"),
                        "station_name": re.sub(r"^YouBike2\.0_", "", row.get("sna", "")),
                        "district": row.get("sarea"), "address": row.get("ar"),
                        "latitude": row.get("latitude", row.get("lat")),
                        "longitude": row.get("longitude", row.get("lng")),
                        "source_update_time": row.get("srcUpdateTime")})
    return records


def load_historical(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    return [{"station_id": row.get("Station Number"), "station_name": row.get("Station"),
             "district": row.get("Station Area"), "address": row.get("Area"),
             "latitude": row.get("Latitude"), "longitude": row.get("Longitude")} for row in rows]


def match_group(names, snapshots):
    names = sorted(set(names))
    result = {"input_name_count": len(names)}
    for label, records in snapshots.items():
        known = {str(row["station_name"]).strip() for row in records if str(row["station_name"]).strip()}
        matched = sorted(set(names) & known)
        result[label] = {"exact_match_count": len(matched), "unmatched_count": len(names) - len(matched),
                         "matched_names": matched}
    return result


def suffix_pairs(names, snapshots):
    output = {}
    for label, records in snapshots.items():
        by_name = defaultdict(list)
        for row in records:
            by_name[str(row.get("station_name", "")).strip()].append(str(row.get("station_id", "")).strip())
        output[label] = []
        for suffixed in sorted(set(names)):
            base = re.sub(r"_\d+$", "", suffixed)
            output[label].append({"suffixed_name": suffixed, "suffixed_ids": sorted(by_name[suffixed]),
                                  "base_name": base, "base_ids": sorted(by_name[base]),
                                  "both_present": bool(by_name[suffixed] and by_name[base]),
                                  "ids_are_disjoint": bool(by_name[suffixed] and by_name[base] and
                                                           set(by_name[suffixed]).isdisjoint(by_name[base]))})
    return output


def compare_snapshots(older, newer):
    old = {str(row["station_id"]): row for row in older}
    new = {str(row["station_id"]): row for row in newer}
    common = sorted(set(old) & set(new))
    changed_names = [station_id for station_id in common
                     if old[station_id]["station_name"] != new[station_id]["station_name"]]
    moved = [station_id for station_id in common
             if (str(old[station_id]["latitude"]), str(old[station_id]["longitude"])) !=
                (str(new[station_id]["latitude"]), str(new[station_id]["longitude"]))]
    return {"common_station_ids": len(common), "same_name_count": len(common) - len(changed_names),
            "changed_name_count": len(changed_names), "changed_name_examples": [
                {"station_id": station_id, "older_name": old[station_id]["station_name"],
                 "newer_name": new[station_id]["station_name"]} for station_id in changed_names[:50]],
            "coordinate_changed_count": len(moved), "coordinate_changed_station_ids": moved,
            "only_older_ids": len(set(old) - set(new)), "only_newer_ids": len(set(new) - set(old)),
            "interpretation_limit": "Two snapshots do not establish valid_from/valid_to or the date of a change."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--historical", type=Path, required=True)
    parser.add_argument("--trip-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    current, historical = load_current(args.current), load_historical(args.historical)
    trip = json.loads(args.trip_evidence.read_text(encoding="utf-8"))["trips"]["station_names"]
    snapshots = {"historical_2024_05_31": historical, "current_2026_09_13": current}
    groups = {
        "replacement_character": trip["replacement_character_names"],
        "question_mark": trip["question_mark_names"],
        "unbalanced_parentheses": trip["unbalanced_parentheses_names"],
        "numeric_suffix": trip["numeric_suffix_names"],
        "destination_only": trip["only_destination"],
    }
    suffix_bases = [re.sub(r"_\d+$", "", name) for name in trip["numeric_suffix_names"]]
    output = {
        "files": {"current": fingerprint(args.current), "historical": fingerprint(args.historical)},
        "snapshots": {
            "current_2026_09_13": profile(current, "official current real-time snapshot",
                "https://tcgbusfs.blob.core.windows.net/dotapp/youbike/v2/youbike_immediate.json", "2026-09-13"),
            "historical_2024_05_31": profile(historical, "third-party capture of official real-time feed",
                "https://github.com/LittleFish-Coder/youbike-info-collector/blob/master/result/2024-05-31.csv", "2024-05-31"),
        },
        "matching": {label: match_group(names, snapshots) for label, names in groups.items()},
        "numeric_suffix_base_probe": match_group(suffix_bases, snapshots),
        "numeric_suffix_pair_details": suffix_pairs(trip["numeric_suffix_names"], snapshots),
        "cross_snapshot_comparison": compare_snapshots(historical, current),
        "matching_note": "Exact string feasibility only. Current names remove only the documented YouBike2.0_ prefix. No station names were merged or changed.",
    }
    save(args.output, output)
    print(f"Station metadata audit saved to {args.output}")


if __name__ == "__main__":
    main()
