# Phase 8.0｜BRouter report evidence

## Evidence classification

| Item | Classification | Evidence |
| --- | --- | --- |
| BRouter is used to simulate routes | Report-specified | R p.5–7 and p.29 |
| Profile is Trekking／旅遊自行車 | Report-specified | R p.29 |
| OD trip-flow weight is assigned to the simulated path | Report-specified | R p.7 and p.29 |
| Flows on overlapping road sections are summed | Report-specified | R p.29 |
| Only default routes were examined | Report-specified | R p.44 |
| Weekday and holiday road-flow maps and segment summaries are separate | Report-specified output | R p.29–31, figures 20–21 and tables 1–2 |
| Routing uses the 2023–2024 core network | Report-implied | R p.7 establishes the core analysis period and p.31 begins the 2023–2024 accident section, but p.29 does not restate the routing period |
| Each unique directed OD pair is routed once | Implementation unspecified in report | No executable unit or request log is preserved |
| BRouter/profile/OSM versions, routing date and graph snapshot | Implementation unspecified in report | Not found in methods, results, appendices, captions or future-work section |
| Station coordinate source and snapping tolerance | Implementation unspecified in report | Not reported |
| Segment directionality, identity and repeated traversal rule | Implementation unspecified in report | “重疊路段” is not operationally defined |
| Failure, retry, timeout and cache policies | Implementation unspecified in report | Not reported |

The report's “default route” statement does not establish which BRouter release, which default `trekking.brf`, or which `.rd5` graph was used. Current official BRouter materials therefore inform the reconstruction contract only; they are not evidence of the historical implementation.

## External implementation evidence

Current official BRouter documentation identifies v1.7.10 as a pinned release, distributes a tagged `trekking.brf`, uses 5°×5° `.rd5` routing tiles, and exposes GeoJSON LineString geometry through the local server. Standard GeoJSON does not expose a stable graph-native edge identifier. The geometry-pair segment identity in this project is consequently a reconstruction fallback and must be validated on real local routes before full execution.

Official sources inspected on 2026-09-18:

- BRouter GitHub release v1.7.10 and repository documentation.
- Tagged `misc/profiles2/trekking.brf` at v1.7.10.
- Official `segments4` index; Taipei/New Taipei spans `E120_N20.rd5` and `E120_N25.rd5`, whose index timestamps were 2026-09-18 CET.

Temporal limitation: **Road topology may differ from the graph available to the original study.**
