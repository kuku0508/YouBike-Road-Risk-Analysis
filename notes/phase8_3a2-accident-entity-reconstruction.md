# Phase 8.3A-2 — Accident entity reconstruction contract

## Scope and result

This phase resolves the accident-entity blocker identified in Phase 8.3A. It uses the official-looking yearly spot-map files as a **candidate event backbone**, then links their rows to the existing party-level casualty files with a deterministic, fail-closed contract. It does not perform road matching, nearest-road search, BRouter-segment matching, distance-threshold selection, EPDO, CBI, risk ranking, or Phase 8.3B.

Labels used below:

- **FACT** — directly established from the preserved source bytes or an existing locked artifact.
- **OBSERVATION** — measured from the reconstruction outputs.
- **RECONSTRUCTION DECISION** — an explicit method chosen for this reconstruction.
- **ASSUMPTION** — accepted operationally despite incomplete source metadata.
- **UNRESOLVED** — not safely determined and therefore excluded rather than guessed.

Machine-readable details and hashes are in `notes/phase8_3a2-accident-entity-reconstruction.json`.

## Source audit and event grain

| Year | Spot-map rows | Columns | Encoding | Handling type 1 | Handling type 2 | Exact duplicate rows |
|---|---:|---:|---|---:|---:|---:|
| 2023 (112) | 24,272 | 5 | CP950, strict | 61 | 24,211 | 1 |
| 2024 (113) | 22,368 | 5 | CP950, strict | 68 | 22,300 | 1 |

Both spot-map files have the exact header `發生時間`, `處理別`, `肇事地點`, `座標-X`, `座標-Y`. Neither contains party fields or a formal accident ID. The 2023 file has one row missing one or both coordinates; the 2024 file has none. No replacement decoding or malformed-row dropping was used.

**FACT:** the spot-map row grain is much closer to an accident event than the party-detail row grain.

**OBSERVATION / collision gate:** a raw spot-map row is not guaranteed to be a unique event. Each year contains one exact duplicate spot row. Therefore the files are a candidate event backbone only; duplicate canonical keys are classified as ambiguous and never silently deduplicated or tie-broken.

## Deterministic identity and crosswalk contract

Primary matching key:

1. exact minute-level event datetime;
2. location text after comparison-only Unicode NFC and outer whitespace trimming;
3. exact numeric decimal X representation;
4. exact numeric decimal Y representation.

Raw location and coordinate strings remain in the output. The primary contract does not round coordinates, use row order, fuzzy matching, substring matching, nearest coordinates, or forced tie-breaking.

For a key to become one reconstructed accident, it must contain exactly one spot-map candidate and exactly one party group, with internally consistent casualty counts and handling type. All other states are explicit:

- `unmatched_spot_event`
- `unmatched_party_group`
- `ambiguous_duplicate_spot_event`
- `severity_conflict`
- `handling_type_conflict`

The stable ID is:

`reconstructed_accident_` + SHA-256 of the compact UTF-8 JSON canonical key.

It is a reconstruction artifact, not an official accident ID. It is deterministic and independent of source-row order.

## Crosswalk results

| Result | 2023 | 2024 | Total |
|---|---:|---:|---:|
| Exact 1:1 reconstructed accidents | 24,220 | 22,366 | 46,586 |
| Unmatched spot-map keys | 50 | 0 | 50 |
| Unmatched party groups | 110 | 1 | 111 |
| Ambiguous duplicate spot keys | 1 | 1 | 2 |
| Spot rows inside ambiguous keys | 2 | 2 | 4 |

Exact 1:1 coverage is 99.7858% of 2023 spot rows, 99.9911% of 2024 spot rows, and 99.8842% overall. The accepted entity artifact contains 46,586 rows and 46,586 unique, non-null reconstructed IDs.

The exact, 8-decimal and 7-decimal sensitivity checks are identical. Six-decimal rounding would add one 2023 match, but it is not accepted into the primary reconstruction because the equality is created by rounding rather than source-exact evidence.

## Duplicate collisions and severity promotion

The 2023 duplicate key occurs at `2023-05-10 19:48`, `北投區稻香路79-2號`. Two identical spot rows correspond to one four-row party group whose repeated casualty fields are inconsistent. It remains an ambiguous duplicate and is excluded from the reconstructed entity table. This is the single Phase 8.3A severity-conflict party group; it was not repaired or resolved by row order.

The 2024 duplicate key occurs at `2024-09-28 12:46`, `文山區興隆路4段66號前`. Two identical spot rows correspond to one two-row party group, while another two-row party group at the same time and location has blank coordinates and remains unmatched. These records also fail closed.

**RECONSTRUCTION DECISION:** accident-level `死亡人數`, `2-30日死亡人數`, and `受傷人數` are promoted exactly once only when every party row in an accepted 1:1 group agrees. All-blank counts remain missing; mixed or inconsistent values are conflicts. Eleven accepted entities have missing severity, and two retain a party-sequence quality flag. A sequence gap does not itself invent or split an event once exact 1:1 identity is established.

For accepted records, handling type and severity are internally coherent: no type-1 event has non-positive 24-hour death count and no type-2 event has a positive 24-hour death count. This is a consistency check, not a substitute for source definitions.

## CRS contract and study-area sanity check

**ASSUMPTION:** the accident X/Y fields are treated operationally as WGS84 longitude/latitude (`EPSG:4326`) for this reconstruction. Phase 8.3A established strong numeric and metadata support but not explicit source CRS metadata; this remains an analyst reconstruction assumption rather than a verified source fact.

For QA only, 46,639 coordinate-complete spot rows were transformed to TWD97 / TM2 zone 121 (`EPSG:3826`). Their transformed bounding box is:

`[295756.6915, 2761989.7713, 315058.4922, 2786750.2488]`

The >8 m road reference bounding box is:

`[296583.6733, 2763248.1991, 313075.2283, 2785444.3727]`

The bounding boxes overlap, providing a study-area sanity check only. No point-in-polygon, nearest-road attribution, or road matching was performed.

## Artifacts and reproducibility

- Crosswalk: `data/interim/accidents/accident_entity_crosswalk_2023_2024.parquet`
  - 46,749 rows
  - content fingerprint: `7fd43e5809b9962562b61e5de8a196cb575cc7e65ccc420f65ef6e157ab75f16`
- Accepted entities: `data/processed/accidents/accident_entities_2023_2024.parquet`
  - 46,586 rows
  - content fingerprint: `ded355d1b5791ea3f2146c51d0321984b4d75ba9e0ff17fb20b8cf9a7b210923`

Both Parquet artifacts are local, derived data and remain Git ignored. The committed receipt records source SHA-256 values, row counts, schemas, classifications, sensitivities, artifact hashes, CRS assumption, and prohibited-work assertions.

## Readiness and disclosed exclusions

**ACCIDENT ENTITY RECONSTRUCTION: READY WITH DISCLOSED EXCLUSIONS FOR EXACT 1:1 SUBSET**

**PHASE 8.3B: READY WITH DISCLOSED EXCLUSIONS**

The accident-entity blocker is resolved for 46,586 exact 1:1 events. Phase 8.3B must preserve and report, rather than silently drop:

- 50 unmatched spot-map event keys;
- 111 unmatched party groups;
- 2 ambiguous duplicate spot keys containing 4 source spot rows;
- the CRS reconstruction assumption;
- road-reference coverage limited to roads wider than 8 metres.

This readiness does not authorize EPDO, CBI, accident-risk ranking, or road attribution in Phase 8.3A-2. Those remain separate downstream decisions.
