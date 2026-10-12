# Phase 8.0｜BRouter / Road-Segment Routing Reconstruction Contract

## Status

**ROUTING COORDINATES FINALIZED — PHASE 8.1 READY WITH DISCLOSED EXCLUSIONS**

Phase 8.0 originally defined `road-routing-contract-v1`. Phase 8.0C advances the coordinate component to backward-compatible `road-routing-contract-v1.1`; it still does not execute full routing or produce a road-flow network.

## Routing universe and period

Primary reconstruction uses the Phase 4.1 core 2023–2024 aggregate under `od-inclusion-policy-v1`: 1,125,519 unique directed OD edges, 2,782 nodes and 91,138,763 trips. This period is a reconstruction decision supported but not explicitly restated by the report's routing section. Each non-self unique directed OD pair is routed once and its full `trip_count` is assigned to every directed segment traversal.

Self-loops are not routed because equal station endpoints cannot identify the traveled road. Their 1,504 edges and 6,023,568 trips remain explicitly accounted; the routing denominator is 1,124,015 non-self edges and 85,115,195 trips.

## Coordinates

Coordinates join only by exact canonical station ID. No station-name geocoding or fuzzy matching is allowed. Phase 8.0B established that `active_station_all.csv` is not sufficiently traceable to qualify as verified historical evidence; that conclusion remains unchanged. Phase 8.0C adds the separate analyst assumption `routing-coordinate-assumption-v1`, under which exact-mapped monthly coordinates are operationally accepted while retaining `evidence_status=supporting_unverified_provenance`.

Source precedence is verified direct historical evidence, analyst-accepted legacy monthly coordinate, existing accepted temporally bracketed coordinate, then unresolved. No verified direct source covering the core period was available. The final immutable artifact contains 2,756 nodes. It covers 1,100,919/1,124,015 non-self OD edges and 83,693,979/85,115,195 trips. The remaining 26 nodes, 23,096 edges and 1,421,216 trips are preserved in explicit gap/unroutable artifacts and must remain separate denominators in Phase 8.1.

No within-period coordinate changes were observed in the accepted legacy reconstruction source. This is not a claim that no station relocation occurred. No coordinate-era artifact is required, so the unique-directed-OD routing unit remains. If verified later evidence establishes an in-period move, create a versioned coordinate artifact, invalidate affected cache entries and route the affected OD × coordinate-era combinations.

## BRouter environment

The local environment is pinned to BRouter v1.7.10, Java 25.0.4.1, the tagged unmodified `trekking.brf`, and official 2026-09-18 `.rd5` tiles `E120_N20` and `E120_N25`. Release ZIP, JAR, profile and both tiles have independent SHA-256 identities in the receipt. Public online routing endpoints were not used.

## Endpoint and route semantics

- Input/output coordinates: EPSG:4326 longitude, latitude.
- BRouter performs graph matching. If corrected waypoints are exported, retain them.
- QA measures geodesic offset from each input endpoint to the first/last route coordinate and reports `<=25`, `25–50`, `50–100`, and `>100 m`; these are descriptive bins, not deletion thresholds.
- Reciprocal OD pairs route independently. No reverse-path assumption or pre-routing merge is permitted.
- Successful route records preserve IDs, weight, status, distance, geometry reference, ordered segment count, route hash, cache key and provenance.

## Segment identity

Graph-native edge IDs are preferred if an executable output can expose them. Standard BRouter GeoJSON evidence presently exposes LineString geometry but no stable graph edge ID. The fallback is an ordered pair of adjacent route vertices rounded half-up to six decimal places and serialized as fixed-decimal `lon,lat->lon,lat`. Reverse traversal is a distinct ID.

Six decimals is approximately decimetre-scale in Taipei and prevents meaningless floating serialization differences. It does **not** prove that two separately generated polylines share identical vertex segmentation. That property remains part of bounded real-route validation; full routing is forbidden until it passes.

The bounded sample produced identical canonical route hashes and distances on rerun. No within-route repeated directed segment was observed. This supports the parser and identity implementation for the sample but does not convert geometry pairs into graph-native IDs.

## Flow, failures and conservation

For OD weight `w` and ordered path `e1…ek`, every traversal receives `w`; weight is never divided by `k`. If a route traverses the same directed segment twice, it receives `2w` under traversal-based counting.

Statuses are `success`, `self_loop_not_routed`, `missing_coordinate`, `coordinate_conflict`, `no_route`, `brouter_error`, `malformed_output`, `snap_anomaly`, and `timeout`. Failures are per-OD fail-closed and must preserve OD weight and error provenance. The valid conservation identity is:

`successful OD weight + failed/unrouted non-self weight + excluded self-loop weight = routing input weight`.

The sum of segment flows is intentionally not equal to total trips.

## Cache and checkpoint

The cache key hashes both station IDs and coordinates, BRouter version, all graph hashes, profile hash and contract version. Resume requires both exact cache identity and output SHA-256. File existence alone never authorizes a skip.

The route and segment schemas, failure taxonomy and immutable parameters are machine-readable in [`routing_contract.yaml`](../config/routing_contract.yaml).
