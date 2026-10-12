"""Profile OD eligibility without constructing OD edges or modifying cleaned data."""
from __future__ import annotations

import argparse
import base64
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

POLICY_VERSION = "od-inclusion-policy-v1"
PRECEDENCE = (
    "quarantined", "missing_endpoint", "identity_ambiguous",
    "identity_unresolved", "candidate_only", "name_collision",
    "no_unique_station_id", "od_eligible",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_identity_evidence(current_path: Path, historical_path: Path,
                           universe_path: Path, metadata_evidence_path: Path) -> dict[str, Any]:
    metadata_evidence = json.loads(metadata_evidence_path.read_text(encoding="utf-8"))["files"]
    expected = {"current": metadata_evidence["current"]["sha256"],
                "historical": metadata_evidence["historical"]["sha256"]}
    observed = {"current": sha256_file(current_path), "historical": sha256_file(historical_path)}
    if observed != expected:
        raise RuntimeError("station metadata hash differs from Phase 2.5 evidence")
    identities: dict[str, set[tuple[str, str]]] = defaultdict(set)
    current = json.loads(current_path.read_text(encoding="utf-8"))
    for row in current:
        name = row["sna"].removeprefix("YouBike2.0_")
        identities[name].add((row["sno"], "Taipei"))
    with historical_path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            identities[row["Station"]].add((row["Station Number"], "Taipei"))
    unique_names = {name: next(iter(values)) for name, values in identities.items() if len(values) == 1}
    collision_names = {name: sorted(values) for name, values in identities.items() if len(values) > 1}
    universe = {}
    with universe_path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if row["decision"] == "not_an_error":
                universe[row["raw_value_base64"]] = (row["station_id"], row["city"])
    return {"unique_names": unique_names, "collision_names": collision_names,
            "station_universe": universe,
            "source_hashes": {"current_metadata": observed["current"],
                              "historical_metadata": observed["historical"],
                              "station_universe": sha256_file(universe_path),
                              "metadata_evidence": sha256_file(metadata_evidence_path)}}


def classify_endpoint(status: str, raw_value: str, station_id: str | None,
                      raw_base64: str, evidence: dict[str, Any]) -> tuple[str, str | None, str | None]:
    """Return mutually exclusive endpoint class plus resolved ID and city."""
    if raw_value == "":
        return "ineligible_missing", None, None
    if status == "approved_repair" and station_id:
        return "eligible_unique_id", station_id, None
    if status == "not_an_error":
        identity = evidence["station_universe"].get(raw_base64)
        return (("eligible_unique_id", *identity) if identity and identity[0]
                else ("ineligible_unresolved", None, None))
    if status == "unchanged_no_rule":
        identity = evidence["unique_names"].get(raw_value)
        if identity:
            return "eligible_unique_id", identity[0], identity[1]
        if raw_value in evidence["collision_names"]:
            return "ineligible_name_collision", None, None
        return "eligible_valid_name_no_id", None, None
    mapping = {"candidate_only": "ineligible_candidate_only",
               "ambiguous": "ineligible_ambiguous", "unresolved": "ineligible_unresolved"}
    return mapping.get(status, "ineligible_unresolved"), None, None


def _count(mask) -> int:
    import pyarrow.compute as pc
    return pc.sum(pc.cast(pc.fill_null(mask, False), "int64")).as_py() or 0


def _or(*masks):
    import pyarrow.compute as pc
    value = pc.fill_null(masks[0], False)
    for mask in masks[1:]:
        value = pc.or_kleene(value, pc.fill_null(mask, False))
    return value


def _and(*masks):
    import pyarrow.compute as pc
    value = pc.fill_null(masks[0], False)
    for mask in masks[1:]:
        value = pc.and_kleene(value, pc.fill_null(mask, False))
    return value


def profile(cleaned_root: Path, evidence: dict[str, Any], quarantine_paths: list[Path]) -> dict[str, Any]:
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    unique_names = pa.array(sorted(evidence["unique_names"]), type=pa.string())
    collision_names = pa.array(sorted(evidence["collision_names"]), type=pa.string())
    universe_b64 = pa.array(sorted(evidence["station_universe"]), type=pa.string())
    endpoint_counts = {"origin": Counter(), "destination": Counter()}
    trip_flags = Counter(); precedence = Counter(); variants = Counter(); cities = Counter()
    overlap = Counter(); accepted_count = 0; month_counts = {}
    columns = []
    for side in ("origin", "destination"):
        columns += [f"{side}_station_raw", f"{side}_station_raw_base64", f"{side}_station_id",
                    f"{side}_station_city", f"{side}_station_repair_status"]

    for parquet_path in sorted(cleaned_root.glob("year=*/month=*/cleaned.parquet")):
        month = f"{parquet_path.parent.parent.name.removeprefix('year=')}/" + parquet_path.parent.name.removeprefix("month=")
        month_counter = Counter()
        parquet = pq.ParquetFile(parquet_path)
        for batch in parquet.iter_batches(batch_size=262_144, columns=columns):
            accepted_count += batch.num_rows; month_counter["accepted"] += batch.num_rows
            masks = {}
            for side in ("origin", "destination"):
                raw = batch.column(batch.schema.get_field_index(f"{side}_station_raw"))
                raw_b64 = batch.column(batch.schema.get_field_index(f"{side}_station_raw_base64"))
                station_id = batch.column(batch.schema.get_field_index(f"{side}_station_id"))
                city = batch.column(batch.schema.get_field_index(f"{side}_station_city"))
                status = batch.column(batch.schema.get_field_index(f"{side}_station_repair_status"))
                nonempty_id = _and(pc.invert(pc.is_null(station_id)), pc.not_equal(station_id, ""))
                missing = _or(pc.is_null(raw), pc.equal(raw, ""))
                approved = pc.equal(status, "approved_repair")
                not_error = pc.equal(status, "not_an_error")
                unchanged = pc.equal(status, "unchanged_no_rule")
                candidate = pc.equal(status, "candidate_only")
                ambiguous = pc.equal(status, "ambiguous")
                unresolved = pc.equal(status, "unresolved")
                meta_unique = pc.is_in(raw, value_set=unique_names)
                name_collision = pc.is_in(raw, value_set=collision_names)
                universe_unique = pc.is_in(raw_b64, value_set=universe_b64)
                unique_id = _or(_and(approved, nonempty_id), _and(not_error, universe_unique),
                                _and(unchanged, meta_unique))
                name_no_id = _and(unchanged, pc.invert(missing), pc.invert(meta_unique),
                                  pc.invert(name_collision))
                classes = {
                    "ineligible_missing": missing,
                    "eligible_unique_id": _and(pc.invert(missing), unique_id),
                    "eligible_valid_name_no_id": name_no_id,
                    "ineligible_candidate_only": _and(pc.invert(missing), candidate),
                    "ineligible_ambiguous": _and(pc.invert(missing), ambiguous),
                    "ineligible_unresolved": _and(pc.invert(missing), unresolved),
                    "ineligible_name_collision": _and(pc.invert(missing), unchanged, name_collision),
                }
                for label, mask in classes.items(): endpoint_counts[side][label] += _count(mask)
                masks[side] = {"missing": missing, "unique": unique_id, "name_no_id": name_no_id,
                               "candidate": candidate, "ambiguous": ambiguous,
                               "unresolved": unresolved, "collision": name_collision,
                               "approved": approved, "not_error": not_error, "unchanged": unchanged,
                               "taipei": _or(_and(approved, pc.equal(city, "Taipei")),
                                             _and(unchanged, meta_unique)),
                               "new_taipei": _or(_and(approved, pc.equal(city, "New Taipei")),
                                                 _and(not_error, universe_unique))}
            flags = {
                "missing_endpoint": _or(masks["origin"]["missing"], masks["destination"]["missing"]),
                "both_endpoints_missing": _and(masks["origin"]["missing"], masks["destination"]["missing"]),
                "identity_ambiguous": _or(masks["origin"]["ambiguous"], masks["destination"]["ambiguous"]),
                "identity_unresolved": _or(masks["origin"]["unresolved"], masks["destination"]["unresolved"]),
                "candidate_only": _or(masks["origin"]["candidate"], masks["destination"]["candidate"]),
                "name_collision": _or(masks["origin"]["collision"], masks["destination"]["collision"]),
                "valid_name_no_id": _or(masks["origin"]["name_no_id"], masks["destination"]["name_no_id"]),
                "both_endpoints_unique_id": _and(masks["origin"]["unique"], masks["destination"]["unique"]),
                "cross_city_valid": _or(masks["origin"]["new_taipei"], masks["destination"]["new_taipei"]),
                "approved_repair": _or(masks["origin"]["approved"], masks["destination"]["approved"]),
                "not_an_error": _or(masks["origin"]["not_error"], masks["destination"]["not_error"]),
                "unchanged_no_rule": _or(masks["origin"]["unchanged"], masks["destination"]["unchanged"]),
            }
            for label, mask in flags.items(): trip_flags[label] += _count(mask)
            issue_labels = ("missing_endpoint", "identity_ambiguous", "identity_unresolved",
                            "candidate_only", "name_collision", "valid_name_no_id", "cross_city_valid")
            for left in issue_labels:
                for right in issue_labels:
                    overlap[(left, right)] += _count(_and(flags[left], flags[right]))
            remaining = pc.invert(flags["missing_endpoint"])
            for label in ("identity_ambiguous", "identity_unresolved", "candidate_only", "name_collision"):
                selected = _and(remaining, flags[label]); precedence[label] += _count(selected)
                remaining = _and(remaining, pc.invert(flags[label]))
            no_id = _and(remaining, pc.invert(flags["both_endpoints_unique_id"]))
            precedence["no_unique_station_id"] += _count(no_id)
            eligible = _and(remaining, flags["both_endpoints_unique_id"])
            precedence["od_eligible"] += _count(eligible)
            precedence["missing_endpoint"] += _count(flags["missing_endpoint"])

            safe_name_o = _or(masks["origin"]["unique"], masks["origin"]["name_no_id"])
            safe_name_d = _or(masks["destination"]["unique"], masks["destination"]["name_no_id"])
            hybrid = _and(pc.invert(flags["missing_endpoint"]), safe_name_o, safe_name_d)
            include_candidate = _and(pc.invert(flags["missing_endpoint"]),
                                     _or(safe_name_o, masks["origin"]["candidate"]),
                                     _or(safe_name_d, masks["destination"]["candidate"]))
            broad = _and(pc.invert(flags["missing_endpoint"]),
                         pc.invert(masks["origin"]["collision"]), pc.invert(masks["destination"]["collision"]))
            taipei_only = _and(eligible, masks["origin"]["taipei"], masks["destination"]["taipei"])
            for label, mask in {"primary_id_required_full_universe": eligible,
                                "hybrid_allow_safe_name_fallback": hybrid,
                                "include_candidate_raw_pseudonodes": include_candidate,
                                "broad_raw_pseudonodes": broad,
                                "taipei_only_id_required": taipei_only}.items():
                value = _count(mask); variants[label] += value; month_counter[label] += value
            city_masks = {"Taipei": masks["origin"]["taipei"], "New Taipei": masks["origin"]["new_taipei"]}
            destination_cities = {"Taipei": masks["destination"]["taipei"],
                                  "New Taipei": masks["destination"]["new_taipei"]}
            for ocity, omask in city_masks.items():
                for dcity, dmask in destination_cities.items():
                    cities[f"{ocity}->{dcity}"] += _count(_and(eligible, omask, dmask))
        month_counts[month] = dict(month_counter)

    quarantine = []
    for path in quarantine_paths:
        quarantine += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    precedence["quarantined"] = len(quarantine)
    total = accepted_count + len(quarantine)
    ordered_precedence = {label: precedence[label] for label in PRECEDENCE}
    if sum(ordered_precedence.values()) != total:
        raise RuntimeError(f"precedence counts do not conserve total records: "
                           f"classified={sum(ordered_precedence.values())},total={total}")
    return {
        "policy_version": POLICY_VERSION, "scope": "2023/01-2025/03",
        "total_input_records": total, "accepted_cleaned_records": accepted_count,
        "quarantine_records": len(quarantine),
        "endpoint_taxonomy_counts": {side: dict(values) for side, values in endpoint_counts.items()},
        "trip_flag_counts": dict(trip_flags), "precedence_resolved_counts": ordered_precedence,
        "policy_variant_retained_records": dict(variants),
        "primary_city_flow_record_counts": dict(cities),
        "issue_overlap_matrix": {left: {right: overlap[(left, right)] for right in (
            "missing_endpoint", "identity_ambiguous", "identity_unresolved", "candidate_only",
            "name_collision", "valid_name_no_id", "cross_city_valid")} for left in (
            "missing_endpoint", "identity_ambiguous", "identity_unresolved", "candidate_only",
            "name_collision", "valid_name_no_id", "cross_city_valid")},
        "monthly": month_counts,
        "identity_evidence": {"unique_exact_metadata_names": len(evidence["unique_names"]),
                              "metadata_name_collisions": len(evidence["collision_names"]),
                              "station_universe_exact_ids": len(evidence["station_universe"]),
                              "source_hashes": evidence["source_hashes"]},
        "notes": ["No OD pair grouping or edge aggregation was performed.",
                  "Quarantine has precedence and is not reclassified into secondary endpoint flags.",
                  "Primary counts require both endpoints to resolve to one canonical station ID."],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cleaned-root", type=Path, required=True)
    parser.add_argument("--current-metadata", type=Path, required=True)
    parser.add_argument("--historical-metadata", type=Path, required=True)
    parser.add_argument("--station-universe", type=Path, required=True)
    parser.add_argument("--metadata-evidence", type=Path, required=True)
    parser.add_argument("--cleaning-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence = load_identity_evidence(args.current_metadata, args.historical_metadata,
                                      args.station_universe, args.metadata_evidence)
    quarantine = sorted(args.cleaned_root.glob("year=*/month=*/quarantine.jsonl"))
    result = profile(args.cleaned_root, evidence, quarantine)
    manifest = json.loads(args.cleaning_manifest.read_text(encoding="utf-8"))
    if (result["total_input_records"] != manifest["global"]["total_input_records"] or
            result["accepted_cleaned_records"] != manifest["global"]["total_accepted_records"] or
            result["quarantine_records"] != manifest["global"]["total_quarantine_records"]):
        raise RuntimeError("eligibility profile does not reconcile to formal cleaning manifest")
    result["identity_evidence"]["source_hashes"]["cleaning_manifest"] = sha256_file(args.cleaning_manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "total": result["total_input_records"],
                      "primary": result["policy_variant_retained_records"]["primary_id_required_full_universe"]},
                     ensure_ascii=True))


if __name__ == "__main__":
    main()
