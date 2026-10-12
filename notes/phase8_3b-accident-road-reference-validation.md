# Phase 8.3B — Accident-to-road reference matching contract and coverage validation

## Scope

This phase validates the spatial relationship between the 46,586 reconstructed accident entities and the official `Road.shp` reference. It does **not** assign a final `ROAD_ID`, select a nearest road, choose a distance threshold, use `TT` or `INTERSECT` to resolve ambiguity, join Phase 8.2 flow, match BRouter segments, calculate EPDO or CBI, rank risk, or start Phase 8.3C.

Labels used here:

- **FACT** — established from locked source bytes or declared source metadata.
- **OBSERVATION** — measured from the bounded validation output.
- **RECONSTRUCTION ASSUMPTION** — accepted operationally despite incomplete source metadata.
- **ANALYTICAL DECISION** — an explicit analysis contract, not a source fact.
- **UNRESOLVED** — deliberately left for a later human policy decision.

The machine-readable receipt is `notes/phase8_3b-accident-road-reference-validation.json`.

## Locked inputs and conservation

The Phase 8.3A-2 entity artifact was revalidated before spatial work:

- rows: 46,586;
- reconstructed IDs: 46,586 unique and non-null;
- entity content fingerprint: `ded355d1b5791ea3f2146c51d0321984b4d75ba9e0ff17fb20b8cf9a7b210923`;
- Parquet SHA-256: `3b82df95f59e5725c84c4f05fff7c785795f66d3e76b7580108a598613497d29`.

**OBSERVATION:** one accepted 2023 entity has blank X and Y. It remains in the one-row-per-accident output as `coordinate_unavailable`; no coordinate was invented and it was not mislabeled as `contained_zero`. The spatially evaluable denominator is therefore 46,585, while the full artifact still conserves all 46,586 reconstructed entities.

The previously disclosed 50 unmatched spot keys, 111 unmatched party groups and 2 ambiguous duplicate spot keys were not added back.

## Road geometry and identifier gate

All locked Shapefile component hashes match the Phase 8.3A receipt. The layer has:

| Check | Result |
|---|---:|
| Features | 13,419 |
| CRS | EPSG:3826, TWD97 / TM2 zone 121 |
| Polygon geometries | 13,419 |
| OGC-valid geometries | 13,419 |
| Empty geometries | 0 |
| Invalid geometries | 0 |
| Unique nonblank `ROAD_ID` | 13,418 |
| Blank `ROAD_ID` | 1 |

Full OGC validity was evaluated with Shapely, including validity reasons for any prospective failure. No `buffer(0)`, `make_valid`, simplification, or other repair was performed.

**FACT:** the layer covers roads wider than 8 metres. It is a physical road-context reference, not the complete Taipei road universe and not a replacement for BRouter segments.

## CRS and containment contract

**RECONSTRUCTION ASSUMPTION:** accident X/Y are operationally treated as WGS84 longitude/latitude (`EPSG:4326`). The source metadata does not explicitly declare this EPSG code.

Accident coordinates were transformed to EPSG:3826 before every polygon and distance operation. No Euclidean distance was calculated in longitude/latitude degrees.

**ANALYTICAL DECISION:** containment uses `polygon.covers(point)`. A point strictly inside a polygon or on its boundary is covered. Candidate sets are deterministically sorted and never resolved by index traversal order, `TT`, `INTERSECT`, `ROADWIDTH`, `ROADNAME`, polygon area, or first match.

## Coverage results

| Spatial status | Count | % of all 46,586 | % of 46,585 spatially evaluable |
|---|---:|---:|---:|
| `contained_unique` | 37,884 | 81.3206% | 81.3223% |
| `contained_multiple` | 0 | 0.0000% | 0.0000% |
| `contained_zero` | 8,701 | 18.6773% | 18.6777% |
| `coordinate_unavailable` | 1 | 0.0021% | — |

Among unique containment results:

- 37,859 accidents are covered by a polygon with a valid `ROAD_ID` (81.2669% of all reconstructed accidents);
- 25 accidents are covered by the single blank-`ROAD_ID` polygon (0.0537%);
- these 25 demonstrate geometry coverage but are not identifiable road attribution successes.

No accident point was covered by multiple polygons. Consequently the observed multiple-candidate distributions for 2, 3 and 4+ polygons are all zero. This is an observed property of these locked inputs and predicates, not a general claim that road polygons never overlap.

## Distance evidence for `contained_zero`

Distances are metres in EPSG:3826 and describe proximity to polygon geometry. They do not assign a road.

| Statistic | Nearest polygon | Second-nearest polygon | Gap: second − nearest |
|---|---:|---:|---:|
| Min | 0.0010 | 0.4482 | 0.0000 |
| Mean | 77.0770 | 94.6198 | 17.5428 |
| Median / P50 | 37.6753 | 51.8622 | 5.3293 |
| P75 | 74.0675 | 88.5570 | 22.7247 |
| P90 | 138.5570 | 156.6405 | 47.8343 |
| P95 | 256.7226 | 285.4226 | 66.0574 |
| P97.5 | 467.5077 | 498.9796 | 92.3233 |
| P99 | 922.6797 | 979.7524 | 148.2906 |
| Max | 2,954.6824 | 3,053.6785 | 428.3695 |

Thirty `contained_zero` accidents have an exact nearest-distance tie across two or more polygons. They remain unresolved; no tie-break was applied.

### Descriptive radius sensitivity

| Nearest distance | Count | % of `contained_zero` | % of all accidents |
|---|---:|---:|---:|
| ≤1 m | 394 | 4.5282% | 0.8457% |
| ≤3 m | 995 | 11.4355% | 2.1358% |
| ≤5 m | 1,521 | 17.4807% | 3.2649% |
| ≤10 m | 2,298 | 26.4108% | 4.9328% |
| ≤20 m | 3,183 | 36.5820% | 6.8325% |
| ≤30 m | 3,849 | 44.2363% | 8.2621% |
| ≤50 m | 5,416 | 62.2457% | 11.6258% |

These bins are descriptive sensitivity evidence only. No value is the formal matching threshold.

## Interpretation and analytical risk

`contained_zero` does not mean the accident is erroneous or off-road. Plausible, unresolved explanations include roads narrower than 8 metres, alleys, other roads outside this reference layer, source-coordinate limitations, and geometry boundary differences. The 18.68% outside-reference share is materially large enough that a later policy cannot silently discard it without risking systematic bias.

The 25 blank-identifier cases show a separate distinction: polygon geometry coverage is not identical to identifiable-road coverage. Future attribution must preserve this state.

`TT`, `INTERSECT`, and `ROADNAME` are retained in the bounded output for QA only. Their undocumented semantics and address-text agreement were not used to select a candidate.

## Artifacts and determinism

- Local Git-ignored validation table: `data/interim/accidents/accident_road_reference_validation_2023_2024.parquet`
  - 46,586 rows
  - content fingerprint: `3cfb32dec6813e4b0e0e1852ff35c999c619cf96c4824ba175c20fc989e418d9`
  - Parquet SHA-256: `313bb429e594cd93ded17326f0a4fbfc191789252635bd7214a70b08eaed52ee`
- Deterministic QA sample: `notes/phase8_3b-accident-road-reference-qa-sample.csv`
  - 36 rows
  - SHA-256: `871b6bf30d622ee3f45b2757d9936bd155560a0ef34d7bf9289702c30c29e61a`

An exact rerun reproduced the receipt fingerprint, output fingerprint, Parquet hash and QA-sample hash. A separate brute-force check of 100 deterministic outside points against all 13,419 polygons exactly reproduced both nearest and second-nearest distances.

## Phase 8.3C readiness

**PHASE 8.3C: READY FOR HUMAN POLICY DECISION WITH DISCLOSED COVERAGE LIMITATIONS**

The evidence is sufficient for an analyst to decide later:

- whether a nearest-road fallback is appropriate;
- which distance thresholds, if any, should be evaluated or accepted;
- how blank identifiers and any future multiple candidates should be handled;
- how `outside_reference_coverage` must be represented.

This status does not select any of those policies. Phase 8.3B stops before formal road attribution, Phase 8.2 flow integration, EPDO, CBI, or risk analysis.
