"""Phase 8.0C deterministic routing-coordinate finalization.

This module operationalizes an explicit analyst assumption.  It does not
promote the legacy source to verified historical evidence and never invokes
BRouter.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd


ASSUMPTION_ID = "routing-coordinate-assumption-v1"
EXPECTED_LEGACY_HASH = "8bf19851f7e9329b0f7207f84b149ce243ca9f6d1e6270ffb5f382b1a9e63205"
EXPECTED_MAPPING_HASH = "52513e958338c87b4e09bb2de4b9b9113b367b5549043d796c1c5990e2b52c66"
CONTRACT_VERSION = "road-routing-contract-v1.1"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fingerprint(frame: pd.DataFrame, columns: list[str]) -> str:
    ordered = frame[columns].astype(str).sort_values(columns, kind="stable")
    payload = ordered.to_csv(index=False, lineterminator="\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_assumption(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value["assumption_id"] != ASSUMPTION_ID:
        raise ValueError("unexpected coordinate assumption ID")
    if value["evidence_status"] == "verified_historical_evidence":
        raise ValueError("analyst override cannot promote evidence status")
    if value["routing_acceptance"] != "accepted_by_analyst_assumption":
        raise ValueError("unexpected routing acceptance")
    return value


def validate_hashes(source: Path, mapping: Path, assumption: dict) -> None:
    source_hash = sha256_file(source)
    mapping_hash = sha256_file(mapping)
    if source_hash != assumption["source"]["sha256"] or source_hash != EXPECTED_LEGACY_HASH:
        raise ValueError("legacy source hash gate failed")
    if mapping_hash != assumption["source"]["mapping_sha256"] or mapping_hash != EXPECTED_MAPPING_HASH:
        raise ValueError("legacy mapping hash gate failed")


def coordinate_sequences(evidence: pd.DataFrame) -> pd.DataFrame:
    """Collapse exact-stable monthly coordinates, and identify era-required IDs."""
    rows = []
    for station_id, group in evidence.groupby("station_id", sort=True):
        valid = group.dropna(subset=["longitude", "latitude", "legacy_month"]).copy()
        month_pairs = valid.groupby("legacy_month").apply(
            lambda x: sorted(set(zip(x.longitude.astype(float), x.latitude.astype(float)))),
            include_groups=False,
        )
        competing = int(sum(len(pairs) != 1 for pairs in month_pairs))
        pairs = sorted(set(pair for values in month_pairs for pair in values))
        rows.append({
            "station_id": str(station_id),
            "coordinate_pairs": pairs,
            "distinct_coordinate_pairs": len(pairs),
            "months_with_competing_coordinates": competing,
            "first_supported_month": valid.legacy_month.min() if len(valid) else None,
            "last_supported_month": valid.legacy_month.max() if len(valid) else None,
            "months_supported": int(valid.legacy_month.nunique()),
            "coordinate_era_required": bool(len(pairs) > 1 or competing),
        })
    return pd.DataFrame(rows)


def build_final_coordinates(mapping: pd.DataFrame, evidence: pd.DataFrame,
                            conflicts: pd.DataFrame, od: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    accepted = mapping[mapping.identity_accepted].copy()
    if accepted.canonical_station_id.isna().any() or accepted.canonical_station_id.duplicated().any():
        raise ValueError("accepted legacy mapping must be one-to-one by canonical station ID")
    mapped_ids = set(accepted.canonical_station_id.astype(str))
    scoped = evidence[evidence.station_id.astype(str).isin(mapped_ids)].copy()
    seq = coordinate_sequences(scoped)
    changed = seq[seq.coordinate_era_required]
    if len(changed):
        raise ValueError("accepted source contains coordinate changes; coordinate-era artifact required")
    if (seq.distinct_coordinate_pairs != 1).any():
        raise ValueError("every accepted station must have one serialization-safe coordinate")

    identity = pd.concat([
        od[["origin_station_id", "origin_station_name", "origin_city"]].rename(
            columns={"origin_station_id":"station_id", "origin_station_name":"station_name", "origin_city":"city"}),
        od[["destination_station_id", "destination_station_name", "destination_city"]].rename(
            columns={"destination_station_id":"station_id", "destination_station_name":"station_name", "destination_city":"city"}),
    ], ignore_index=True)
    identity["station_id"] = identity.station_id.astype(str)
    identity = identity.sort_values(["station_id", "station_name", "city"]).drop_duplicates("station_id")
    conflict_ids = set(conflicts.station_id.astype(str))

    rows = []
    for row in seq.itertuples(index=False):
        lon, lat = row.coordinate_pairs[0]
        idrow = identity[identity.station_id == row.station_id].iloc[0]
        rows.append({
            "station_id": row.station_id, "station_name": idrow.station_name, "city": idrow.city,
            "routing_lat": float(lat), "routing_lon": float(lon),
            "coordinate_source": "active_station_all.csv monthly coordinate",
            "evidence_status": "supporting_unverified_provenance",
            "routing_acceptance": "accepted_by_analyst_assumption",
            "analyst_override": True, "coordinate_conflict": row.station_id in conflict_ids,
            "first_supported_month": row.first_supported_month, "last_supported_month": row.last_supported_month,
            "months_supported": row.months_supported, "assumption_id": ASSUMPTION_ID,
            "source_sha256": EXPECTED_LEGACY_HASH, "mapping_sha256": EXPECTED_MAPPING_HASH,
        })
    final = pd.DataFrame(rows).sort_values("station_id").reset_index(drop=True)

    core_ids = sorted(set(od.origin_station_id.astype(str)) | set(od.destination_station_id.astype(str)))
    gaps = identity[identity.station_id.isin(set(core_ids) - set(final.station_id))].copy()
    relevant = pd.concat([
        od[["origin_station_id", "trip_count"]].rename(columns={"origin_station_id":"station_id"}),
        od[["destination_station_id", "trip_count"]].rename(columns={"destination_station_id":"station_id"}),
    ])
    relevant.station_id = relevant.station_id.astype(str)
    impacts = relevant.groupby("station_id").agg(endpoint_od_involvements=("trip_count","size"), endpoint_trip_involvements=("trip_count","sum")).reset_index()
    gaps = gaps.merge(impacts, on="station_id", how="left")
    gaps["identity_mapped_in_legacy"] = gaps.station_id.isin(mapped_ids)
    gaps["coordinate_conflict"] = gaps.station_id.isin(conflict_ids)
    gaps["reason"] = gaps.identity_mapped_in_legacy.map({
        True: "exact_legacy_identity_but_no_valid_legacy_coordinate",
        False: "no_accepted_exact_legacy_mapping_and_no_other_accepted_coordinate",
    })
    return final, gaps.sort_values("station_id").reset_index(drop=True)


def build_unroutable(od: pd.DataFrame, accepted_ids: set[str]) -> pd.DataFrame:
    nonself = od[od.origin_station_id.astype(str) != od.destination_station_id.astype(str)].copy()
    missing_o = ~nonself.origin_station_id.astype(str).isin(accepted_ids)
    missing_d = ~nonself.destination_station_id.astype(str).isin(accepted_ids)
    out = nonself[missing_o | missing_d].copy()
    out["missing_origin_coordinate"] = missing_o[missing_o | missing_d].to_numpy()
    out["missing_destination_coordinate"] = missing_d[missing_o | missing_d].to_numpy()
    out["missing_endpoints"] = out.apply(
        lambda r: "both" if r.missing_origin_coordinate and r.missing_destination_coordinate else
                  ("origin" if r.missing_origin_coordinate else "destination"), axis=1)
    out["reason"] = "coordinate_gap_after_analyst_override"
    return out.sort_values(["trip_count", "origin_station_id", "destination_station_id"], ascending=[False, True, True]).reset_index(drop=True)


def main(args) -> dict:
    root = args.root.resolve()
    assumption = load_assumption(args.assumption)
    validate_hashes(args.source, args.mapping, assumption)
    mapping = pd.read_parquet(args.mapping)
    evidence = pd.read_parquet(args.evidence)
    conflicts = pd.read_parquet(args.conflicts)
    od = pd.read_parquet(args.od)
    final, gaps = build_final_coordinates(mapping, evidence, conflicts, od)
    unroutable = build_unroutable(od, set(final.station_id))

    nonself = od[od.origin_station_id.astype(str) != od.destination_station_id.astype(str)]
    unroutable_weight = int(unroutable.trip_count.sum())
    total_weight = int(nonself.trip_count.sum())
    routable_edges = len(nonself) - len(unroutable)
    routable_weight = total_weight - unroutable_weight
    station_id_fp = fingerprint(final, ["station_id"])
    coordinate_fp = fingerprint(final, ["station_id", "routing_lon", "routing_lat"])
    accepted_conflict_count = int(final.coordinate_conflict.sum())
    unresolved_conflict_count = int(gaps.coordinate_conflict.sum())
    if accepted_conflict_count + unresolved_conflict_count != len(conflicts):
        raise ValueError("not all Phase 8.0A conflicts remain flagged")

    # Write only after every semantic gate passes.  A failed validation must
    # not replace the finalized artifacts.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    final.to_parquet(args.output, index=False)
    gaps.to_csv(args.gaps, index=False, encoding="utf-8-sig")
    unroutable.to_parquet(args.unroutable, index=False)

    receipt = {
        "phase": "8.0C", "full_routing_executed": False,
        "analyst_decision_id": assumption["decision_id"], "coordinate_assumption_id": ASSUMPTION_ID,
        "legacy_csv_sha256": sha256_file(args.source), "mapping_sha256": sha256_file(args.mapping),
        "provenance_status": "unverified; Phase 8.0B NOT SUFFICIENTLY TRACEABLE conclusion preserved",
        "evidence_status": "supporting_unverified_provenance",
        "routing_acceptance": "accepted_by_analyst_assumption",
        "identity_mapped_station_count": int(mapping.identity_accepted.sum()),
        "accepted_under_assumption_count": len(final), "verified_historical_count": 0,
        "conflict_count": len(conflicts), "accepted_conflict_count": accepted_conflict_count,
        "unresolved_conflict_count": unresolved_conflict_count, "unresolved_core_nodes": len(gaps),
        "within_period_coordinate_changes_observed": 0, "coordinate_era_count": 0,
        "routing_unit": "unique_directed_od_pair", "routing_contract_version": CONTRACT_VERSION,
        "coverage": {
            "accepted_core_nodes": len(final), "total_core_nodes": len(set(od.origin_station_id.astype(str)) | set(od.destination_station_id.astype(str))),
            "node_percentage": len(final) / 2782 * 100,
            "routable_non_self_od_edges": routable_edges, "total_non_self_od_edges": len(nonself),
            "routable_od_percentage": routable_edges / len(nonself) * 100,
            "routable_trip_weight": routable_weight, "total_non_self_trip_weight": total_weight,
            "routable_trip_weight_percentage": routable_weight / total_weight * 100,
            "unroutable_non_self_od_edges": len(unroutable), "unroutable_trip_weight": unroutable_weight,
        },
        "gap_profile": {
            "identity_mapped_but_no_valid_legacy_coordinate": int(gaps.identity_mapped_in_legacy.sum()),
            "no_accepted_exact_identity_mapping": int((~gaps.identity_mapped_in_legacy).sum()),
            "by_city": {str(k): int(v) for k, v in gaps.city.value_counts().sort_index().items()},
            "unroutable_endpoint_pattern": {
                str(k): {"edges": int(len(v)), "trip_weight": int(v.trip_count.sum())}
                for k, v in unroutable.groupby("missing_endpoints", sort=True)
            },
            "top_unresolved_station_ids_by_endpoint_trip_involvement": [
                {"station_id": str(r.station_id), "city": str(r.city),
                 "endpoint_od_involvements": int(r.endpoint_od_involvements),
                 "endpoint_trip_involvements": int(r.endpoint_trip_involvements), "reason": str(r.reason)}
                for r in gaps.sort_values(["endpoint_trip_involvements", "station_id"], ascending=[False, True]).head(10).itertuples()
            ],
            "bias_limitation": "The excluded flow is concentrated in 26 unresolved stations and is not demonstrated to be unbiased; Phase 8.1 must report routed and unroutable denominators separately."
        },
        "self_loops": {"edges": int((od.origin_station_id.astype(str) == od.destination_station_id.astype(str)).sum()),
                       "trip_weight": int(od.loc[od.origin_station_id.astype(str) == od.destination_station_id.astype(str), "trip_count"].sum()),
                       "policy": "excluded_from_BRouter_and_retained_in_conservation_accounting"},
        "artifacts": {
            "final_coordinate": {"path": args.output.relative_to(root).as_posix(), "rows": len(final), "sha256": sha256_file(args.output),
                                 "station_id_fingerprint": station_id_fp, "coordinate_fingerprint": coordinate_fp},
            "core_gap": {"path": args.gaps.relative_to(root).as_posix(), "rows": len(gaps), "sha256": sha256_file(args.gaps)},
            "unroutable_od": {"path": args.unroutable.relative_to(root).as_posix(), "rows": len(unroutable), "sha256": sha256_file(args.unroutable)},
            "coordinate_era": None,
        },
        "cache_invalidation": "coordinate artifact hash and routing contract version are cache-key inputs; prior route cache is stale",
        "readiness_status": "ROUTING COORDINATES FINALIZED — PHASE 8.1 READY WITH DISCLOSED EXCLUSIONS",
    }
    args.receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return receipt


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--source", type=Path, default=root/"data/raw/active_station_all.csv")
    parser.add_argument("--mapping", type=Path, default=root/"data/interim/routing/legacy_station_name_mapping.parquet")
    parser.add_argument("--evidence", type=Path, default=root/"data/interim/routing/legacy_coordinate_evidence.parquet")
    parser.add_argument("--conflicts", type=Path, default=root/"data/interim/routing/routing_coordinate_conflicts.parquet")
    parser.add_argument("--od", type=Path, default=root/"data/processed/od/aggregate/core_2023_2024/od.parquet")
    parser.add_argument("--assumption", type=Path, default=root/"config/routing_coordinate_assumption.yaml")
    parser.add_argument("--output", type=Path, default=root/"data/processed/routing/routing_station_coordinates_2023_2024.parquet")
    parser.add_argument("--gaps", type=Path, default=root/"data/processed/routing/core_routing_coordinate_gap.csv")
    parser.add_argument("--unroutable", type=Path, default=root/"data/processed/routing/unroutable_od_due_to_coordinate_gap.parquet")
    parser.add_argument("--receipt", type=Path, default=root/"notes/routing-coordinate-finalization-receipt.json")
    result = main(parser.parse_args())
    print(json.dumps({"status": result["readiness_status"], "coverage": result["coverage"]}, ensure_ascii=False))
