# Phase 8.3A — Accident data and road reference audit

## Scope

Phase 8.3A is a read-only input audit. It does **not** perform accident-to-road matching, accident-to-BRouter matching, distance-threshold selection, EPDO, CBI, risk ranking, or Phase 8.3B implementation. Phase 8.1 routing artifacts and the Phase 8.2 directed-segment usage table were not modified.

Labels in this note have the following meaning:

- **FACT** — established directly from local raw bytes, declared metadata, or an official source.
- **OBSERVATION** — a measured distribution or recurring data pattern.
- **INFERENCE** — a supported interpretation that is not formally defined by source metadata.
- **UNRESOLVED** — evidence is insufficient for a production contract.

The complete per-column profiles, file hashes, monthly counts, component hashes and machine-readable findings are in `notes/phase8_3a-accident-data-audit.json`.

## Sources and file integrity

### Accident files

| File | Bytes | SHA-256 | Encoding | Rows × columns |
|---|---:|---|---|---:|
| `112年-臺北市死傷交通事故明細.csv` | 10,228,496 | `448859d4191d6c4014583466dd9e6f13b481cc80a0a0ebf3ae00ab2613300ba9` | UTF-8 BOM | 56,139 × 50 |
| `113年-臺北市死傷交通事故明細.csv` | 9,398,043 | `b6ad23f05658531998f34ba4995a190d03872940ea48013115da89bb2a4e92c5` | UTF-8 BOM | 51,810 × 49 |

**FACT:** Both files use comma delimiters, decode strictly as UTF-8, have one header row, no duplicate column names, no completely empty records, no malformed-width records and no completely identical rows. No decoding replacement or malformed-row dropping was used.

**FACT:** The filenames, approximate published sizes and field families agree with the Taipei Open Data page for “臺北市死傷交通事故資料,” provided by the Police Department Traffic Police Division. The current official metadata calls X/Y coordinate-point fields but does not state their CRS or define an accident identifier.

### Road reference

`data/raw/8mroadup` contains `Road.shp`, `Road.shx`, `Road.dbf`, `Road.prj`, `Road.cpg`, and an optional `Road.qmd`. All component sizes and SHA-256 hashes are preserved in the JSON receipt. Required Shapefile components are complete.

**FACT:** The local DBF field list and source description agree with the official Taipei dataset “臺北市寬度超過8公尺道路GIS圖資.” The official metadata says it was built through a 2014–2016 survey project, covers roads wider than 8 metres, and uses TWD97. This source scope is materially narrower than the complete Taipei street universe.

## Accident schema and grain

The two files share 48 columns in the same relative order. Both contain accident context, casualty counts and party-level attributes including `當事人序號`, `車種`, `性別`, `年齡`, `受傷程度`, vehicle use, party action and individual cause codes.

Schema differences:

| Status | Fields |
|---|---|
| 112 only | `光線`, `旅次目的` |
| 113 only | `道路照明設備` |
| Common | 48 fields; complete list in receipt |

**FACT:** The files are not safe to blindly stack because their headers differ.

**UNRESOLVED:** `光線` and `道路照明設備` must not be treated as aliases without authoritative codebook review. The 112-only `旅次目的` also needs an explicit missing-by-schema rule before canonicalization.

### Row unit

**FACT:** A row is a party-level record, not one accident. Evidence includes `當事人序號` and party-specific vehicle, demographic, injury, action and individual-cause fields. Multiple rows repeatedly share the same time, location and coordinates while party sequence changes.

**FACT:** No explicit reliable accident ID is present.

For profiling only, an exploratory key used year/month/day/hour/minute, district, location text and exact X/Y. It is **heuristic only** and was not materialized as a formal accident identifier:

| Measure | 112 | 113 |
|---|---:|---:|
| Heuristic groups | 24,331 | 22,368 |
| Groups with >1 party row | 24,329 | 22,367 |
| Maximum rows in one group | 18 | 27 |
| Groups with contiguous party sequence | 24,328 | 22,368 |
| Groups with inconsistent repeated casualty counts | 1 | 0 |

**UNRESOLVED / blocker:** Timestamp + location + coordinate equality is not proven to be a collision-free accident key. Phase 8.3A therefore does not claim 24,331 and 22,368 formal accident counts.

## Temporal coverage

ROC years were converted for QA only by `western year = ROC year + 1911`, after verifying integer year/month/day/hour/minute fields.

| File | Minimum | Maximum | Missing | Invalid | Years observed |
|---|---|---|---:|---:|---|
| 112 | 2023-01-01 00:46 | 2023-12-31 23:23 | 0 | 0 | 2023 only |
| 113 | 2024-01-01 00:22 | 2024-12-31 23:46 | 0 | 0 | 2024 only |

**FACT:** Every month of each stated year is represented. Exact party-row counts by month are in the receipt.

## Accident location and coordinate quality

| Measure | 112 | 113 |
|---|---:|---:|
| Complete X/Y | 56,136 (99.9947%) | 51,808 (99.9961%) |
| Missing both X/Y | 3 | 2 |
| Invalid numeric X/Y | 0 | 0 |
| Zero-coordinate rows | 0 | 0 |
| Unique coordinate pairs | 23,984 | 22,237 |
| Rows in duplicated coordinate pairs | 56,134 | 51,807 |
| Maximum pair multiplicity | 35 | 74 |

Ranges:

- 112: X 121.4538759–121.6446712; Y 24.96470622–25.18811674
- 113: X 121.4611893–121.6433699; Y 24.96671237–25.18824608

**FACT:** `肇事地點` is populated on every row, including the five rows without coordinates. No record lacks both coordinates and location text.

**OBSERVATION:** Coordinate duplication is expected under party-level grain because parties in the same apparent event share a point. Duplicate coordinates are not classified as errors. Coordinate precision varies mainly between 6–8 decimal places.

**INFERENCE (high confidence, not confirmed CRS):** Numeric ranges and the official description of these fields as coordinate points—and a separate official government description referring to longitude/latitude—strongly suggest geographic longitude/latitude compatible with WGS84. Neither the local files nor their official dataset metadata explicitly declares EPSG:4326. The production CRS remains **UNRESOLVED** until authoritative CRS metadata or a separately approved reconstruction assumption exists.

## Casualty and EPDO feasibility

Available fields include `死亡人數`, `2-30日死亡人數`, `受傷人數`, and party-level `受傷程度`.

| Field | 112 range / nulls | 113 range / nulls |
|---|---|---|
| 死亡人數 | 0–1 / 9 null | 0–3 / 19 null |
| 2-30日死亡人數 | 0–1 / 9 null | 0–1 / 19 null |
| 受傷人數 | 0–8 / 1 null | 0–26 / 2 null |

**OBSERVATION:** Casualty counts repeat across party rows within nearly every heuristic group. This is consistent with accident-level counts duplicated onto each party record, but the missing accident ID prevents formal accident-level deduplication.

**FACT:** No explicit A1/A2/A3 field and no property-damage amount/count field is present in either local file. The official source describes these as casualty accident details; a separate official A3 dataset exists.

**UNRESOLVED / blocker:** Complete EPDO cannot be reconstructed safely from these files alone. Death and injury counts cannot be aggregated at party-row grain, the formal accident key is unresolved, and pure property-damage accidents are not demonstrated to be included. Phase 8.3A did not compute EPDO.

## Road layer audit

| Property | Result |
|---|---|
| Features | 13,419 |
| Geometry | 13,419 Polygon |
| CRS | TWD97 / TM2 zone 121, EPSG:3826, confirmed by `.prj`; TWD97 also confirmed by official metadata |
| Bounding box | X 296,583.6733–313,075.2283; Y 2,763,248.1991–2,785,444.3727 |
| Empty geometries | 0 |
| Structurally invalid geometries | 0 |
| Full OGC topology validity | unresolved; no topology engine used |

**FACT:** These are road polygons, not road centrelines. SHP, SHX and DBF independently agree on 13,419 features. The binary audit confirmed finite coordinates, valid record lengths, polygon part indexes, at least four points per ring and closed rings. It does not claim full OGC topological validity such as absence of self-intersections.

Key DBF findings:

- `ROAD_ID`: present; 13,418 distinct nonblank values, zero duplicated nonblank values, one blank. It is therefore almost unique but fails a strict non-null primary-key contract.
- `ROADNAME`: one blank; 1,720 distinct nonblank values.
- `TOWNNAME`: one blank; 12 distinct nonblank values.
- `ROADWIDTH`: all 13,419 numeric; range 0–102.83.
- `TT`: 7,667 records with `0`, 5,752 with `1`.
- `INTERSECT`: 13,418 nonblank values.

**OBSERVATION:** All `TT=1` features have `ROADWIDTH=0`; most `INTERSECT` strings in both TT groups contain comma-separated identifiers. These patterns may encode different road/intersection feature roles.

**UNRESOLVED:** Neither the official dataset page nor local metadata defines `TT` or `INTERSECT`. No semantic label such as “TT=1 means intersection” is accepted.

## Spatial comparability and readiness

**FACT:** The road layer is a Taipei TWD97 polygon dataset; accident coordinates fall in Taipei-like longitude/latitude ranges and every record has either a coordinate pair or location text. No formal spatial matching was run.

**INFERENCE:** The layers appear to cover the same broad Taipei study area, but they are not yet in a confirmed common CRS and the road source only covers roads wider than 8 metres.

### Phase 8.3B readiness: BLOCKED

The audit itself is complete, but accident-to-road attribution is not yet ready because:

1. accident CRS is a high-confidence candidate, not confirmed;
2. there is no reliable accident ID or approved accident-entity construction rule;
3. the road source omits roads not wider than 8 metres, creating a potentially systematic coverage gap;
4. `TT` / `INTERSECT` semantics remain undocumented;
5. full polygon topology validity has not been established;
6. complete EPDO remains unsupported without an accident key and property-damage population.

The smallest next task is to resolve the accident CRS and accident-entity contract, then decide whether the >8 m road layer is an explicitly acceptable scoped reference or whether a complete authoritative road polygon/centreline layer is required. No distance threshold should be selected before those decisions.

## Official metadata consulted

- Taipei Open Data, `臺北市死傷交通事故資料`: `https://data.taipei/dataset/detail?id=2f238b4f-1b27-4085-93e9-d684ef0e2735`
- Taipei Open Data, `臺北市寬度超過8公尺道路GIS圖資`: `https://data.taipei/dataset/detail?id=ee2e4015-8844-48fb-aa57-31209909b0fc`
