# Phase 8.2 — Directed road-segment usage aggregation

## Scope and authority

Phase 8.2 aggregates the completed Phase 8.1C route cache into directed road-segment usage. It does not rerun BRouter, modify the route cache, integrate accidents, calculate EPDO / CBI, or start Phase 8.3.

The authoritative input is the read-only current-state SQLite cache validated by `notes/phase8_1c-production-completion.json`:

- routes: 1,100,919 successful directed OD routes
- routed trip weight: 83,693,979
- route-state fingerprint: `1a69cd69be3983779d20abc64667936561526d156f363d64bcf7cd49c31d7b37`

Every record is revalidated against its route ID, cache key, stored content hash, recomputed content hash, terminal status, segment count, and day-type weight identity before aggregation. The source database is opened in SQLite read-only mode.

## Segment contract

`directed-segment-usage-v1` uses the ordered adjacent canonical coordinate pair:

`from_lon,from_lat -> to_lon,to_lat`

- longitude and latitude are canonicalized to six decimal places upstream and stored here as signed integer microdegrees (`*_e6`, `int32`);
- direction is retained, so A→B and B→A are different rows;
- consecutive points that become identical after canonicalization must collapse before segment creation;
- a route with fewer than two distinct canonical points fails closed;
- every traversal is retained, including repeated traversal of the same directed segment by one route;
- `unique_route_count` increments at most once per route and segment;
- all counts and flow weights are stored as `int64`.

The authoritative cache stores the already-validated canonical segment sequence rather than the original full-precision GeoJSON coordinates. Therefore Phase 8.2 derives point counts as `segment_count + 1`. The accepted production cache contains no zero-length canonical segments, so the production collapse and prevented-zero-length counts are both zero. Synthetic tests separately exercise original-point canonicalization and consecutive-duplicate collapse.

## Implementation

The implementation is `src/aggregate_road_segment_usage.py`.

- Backend: a separate on-disk SQLite table with composite primary key `(from_lon_e6, from_lat_e6, to_lon_e6, to_lat_e6)` and additive UPSERTs.
- Chunking: 1,000 routes per atomic transaction.
- Resume: the checkpoint stores input fingerprint, chunk size, last route ID, processed route count, and independent counters.
- Output: sorted, streaming PyArrow Parquet export with Zstandard compression.
- Memory discipline: routes and final rows are streamed; the 1.1 million geometries and approximately 195 million traversal occurrences are never materialized together in RAM.

The work database and final Parquet are large runtime artifacts under Git-ignored `data/interim/` and `data/processed/`. The small completion receipt is committed.

## Results

| Measure | Result |
|---|---:|
| Input successful routes | 1,100,919 |
| Unique directed segments | 149,234 |
| Effective segment traversals | 195,336,834 |
| Sum of unique-route counts | 195,336,834 |
| Total weighted traversals | 4,674,227,848 |
| Weekday weighted traversals | 3,307,530,105 |
| Holiday weighted traversals | 1,366,697,743 |
| Derived raw/canonical points | 196,437,753 / 196,437,753 |
| Collapsed consecutive canonical duplicates | 0 |
| Prevented zero-length segments | 0 |
| Runtime | 1,449.759 seconds |

The equal sums for effective traversals and unique-route counts are an observed production result: none of the accepted route sequences traversed the same directed canonical segment more than once. This does not weaken the contract; multiplicity is explicitly implemented and covered by tests.

## Conservation and independent validation

All production invariants passed exactly:

- input route count equals 1,100,919;
- SQLite aggregate traversal sum equals the independently accumulated traversal count;
- SQLite `unique_route_count` sum equals the independently accumulated distinct route–segment count;
- total, weekday, and holiday weighted traversal sums each equal their independent route-level expansions;
- for every output segment, `weekday_trip_weight + holiday_trip_weight = total_trip_weight`;
- the final Parquet has 149,234 rows and 149,234 unique directed composite keys.

An independent PyArrow reread reproduced all five global sums and the day-type identity. Final artifact identities:

- row-value fingerprint: `0925c99aa8f0022c953e09046bd7728d6a546cae6f28c81f68ccb5e35d6b2a04`
- Parquet SHA-256: `68d0dec6498b7734b6cd09c7f94ec20cfa8708de31cbdb898b4ad65a0288f8ad`

## Interpretation boundary

This artifact estimates use/exposure on BRouter-simulated directed road segments. It is not GPS-observed cycling traffic and is not yet an accident-risk measure. Phase 8.3 accident matching, EPDO, CBI, and causal interpretation were not performed.
