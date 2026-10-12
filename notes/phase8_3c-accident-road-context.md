# Phase 8.3C — Accident road-context finalization

## Purpose and boundary

Phase 8.3C converts the verified Phase 8.3B spatial relationships into one deterministic, fail-closed road-context record for every reconstructed accident. `Road.shp` supplies physical road context only. It is not the bicycle-flow layer, a BRouter-segment replacement, or the complete Taipei road universe.

This phase does not use nearest-road fallback, select a distance threshold, match accidents to BRouter segments, join Phase 8.2 flow, geocode addresses, calculate EPDO or CBI, rank risk, or start Phase 8.4.

Labels:

- **FACT** — established from locked source bytes or explicit source metadata.
- **OBSERVATION** — measured from locked artifacts.
- **RECONSTRUCTION ASSUMPTION** — operationally accepted despite incomplete source metadata.
- **ANALYTICAL DECISION** — an explicit project policy rather than a source fact.
- **UNRESOLVED** — deliberately left for a later contract.

## Locked inputs

Finalization verifies before writing:

- Phase 8.3A-2 entity row count, ID uniqueness, Parquet SHA-256 and content fingerprint;
- Phase 8.3B receipt fingerprint, bounded-output SHA-256, content fingerprint and row count;
- all locked Road Shapefile component hashes and EPSG:3826 geometry gate;
- exact equality of Phase 8.3A-2 and Phase 8.3B reconstructed-accident ID sets.

Any mismatch fails closed. Phase 8.3C reads the Phase 8.3B containment results and does not create a second spatial-matching implementation.

## Formal status vocabulary

| Status | Formal meaning | Count | % of all 46,586 |
|---|---|---:|---:|
| `contained_valid_road` | Exactly one polygon covers the point and has a nonblank `ROAD_ID` | 37,859 | 81.2669% |
| `contained_blank_road_id` | Exactly one valid polygon covers the point but `ROAD_ID` is blank | 25 | 0.0537% |
| `outside_reference_coverage` | Coordinate is available but no >8 m road-reference polygon covers it | 8,701 | 18.6773% |
| `coordinate_unavailable` | Reconstructed accident exists but has no usable X/Y | 1 | 0.0021% |
| `contained_multiple` | More than one polygon covers the point; never automatically tie-broken | 0 | 0.0000% |

The exact conservation identity is:

`37,859 + 25 + 8,701 + 1 + 0 = 46,586`.

All 46,586 reconstructed IDs are non-null, unique and exactly equal to the Phase 8.3A-2 ID set. No accident was dropped, duplicated, regenerated or added from the previously disclosed exclusions.

## Formal policy

**ANALYTICAL DECISION:** an identifiable Road.shp context exists only when direct polygon coverage is unique and the polygon has a valid nonblank `ROAD_ID`.

- Nearest-road fallback: **disabled**.
- Formal distance threshold: **none**.
- `ROADNAME` as identifier or fallback: **prohibited**.
- Blank `ROAD_ID` replacement, row-number ID or geometry-hash ID: **prohibited**.
- `contained_multiple` tie-break: **disabled**.
- `TT` / `INTERSECT`: **UNRESOLVED and not used**.

The Phase 8.3B distance evidence supports rejecting a general nearest-road fallback: among 8,701 outside points, nearest-polygon P50/P75/P90 are 37.6753/74.0675/138.5570 metres, and only 1,521 are within 5 metres. Combined with the reference layer's >8 m scope, forcing every outside point onto the nearest included road would turn incomplete reference coverage into false precision. This does not establish that every outside point lies on a narrow road.

`outside_reference_coverage` is not an accident error, invalid record, off-road classification, or deletion candidate. The accident remains part of the canonical population.

## CRS contract

- **FACT:** `Road.shp` is EPSG:3826.
- **RECONSTRUCTION ASSUMPTION:** accident X/Y are operationally treated as WGS84 longitude/latitude, EPSG:4326. This is not confirmed source CRS metadata.
- **ANALYTICAL DECISION:** Phase 8.3B transformed accident coordinates to EPSG:3826 before `covers` evaluation; Phase 8.3C preserves those locked results.

## Canonical dataset

Path: `data/processed/accidents/accident_road_context_2023_2024.parquet`

Grain: one row per reconstructed accident, sorted by `reconstructed_accident_id`.

Schema:

- `reconstructed_accident_id`
- `year`
- `event_datetime`
- `x_raw`, `y_raw`
- `x_epsg3826`, `y_epsg3826`
- `road_context_status`
- `road_id`, `road_name`, `town_name`
- `road_reference_feature_count`
- `crs_assumption`
- `source_accident_entity_fingerprint`
- `source_bounded_validation_fingerprint`
- `source_road_reference_fingerprint`

For `contained_valid_road`, raw Road metadata is retained without name correction or normalization. For `contained_blank_road_id`, `road_id` stays null; the relevant source polygon also has blank `ROADNAME` and `TOWNNAME`, so those remain null. Outside and coordinate-unavailable records receive no road metadata. Coordinate-unavailable derived spatial fields are null.

Nearest, second-nearest and gap fields remain only in the Phase 8.3B diagnostic artifact and are intentionally absent from this canonical dataset.

## Determinism and artifact identity

- Rows: 46,586
- Output fingerprint: `186f751e3a33ff2db01e7e44abe3255fff1008de3e9aaeb35056dd541e6b9f5b`
- Parquet SHA-256: `d64954bf04877776968f7eb8e8bf6755d96c2ea75019d292325234c2df75cfa3`
- Receipt fingerprint: `24298f009a728d6a2a0aba988c6e11a7716e9dcf1d9a2354e714d2606514e896`

An exact rerun reproduced row order, statuses, road metadata, output fingerprint, Parquet SHA-256 and receipt fingerprint. Full Parquet reread and independent ID/status/null-policy checks passed.

## Future interface and readiness

- `contained_valid_road`: Phase 8.4 may use Road.shp context as a constraint when searching BRouter candidates.
- `contained_blank_road_id`: polygon evidence exists, but a separate future policy is required because no valid identifier exists.
- `outside_reference_coverage`: remains eligible for a future BRouter candidate policy without Road.shp context constraint; it must not be excluded.
- `coordinate_unavailable`: cannot enter spatial matching without a separately authorized geocoding contract.
- `contained_multiple`: schema support is retained and remains fail-closed if future data produces it.

**PHASE 8.4: READY WITH FORMAL ROAD-CONTEXT STATES AND DISCLOSED REFERENCE LIMITATIONS**

This is interface readiness only. Phase 8.4 has not started, and no accident has been assigned to a BRouter segment or combined with bicycle-flow exposure.
