# Phase 8.0｜Bounded routing validation

## Sample definition

A deterministic candidate sample was generated from the core OD table: 20 non-self pairs plus one self-loop exclusion case. It includes high/middle/low flow, Taipei→New Taipei, a reciprocal pair, shortest and longest coordinate-distance candidates, and deterministic fill rows. The exact list and SHA-256 are in the validation receipt.

## Execution result

The pinned local BRouter v1.7.10 environment routed the precommitted sample twice with the unmodified Trekking profile and official 2026-09-18 graph tiles.

| Check | Result |
| --- | ---: |
| Non-self routes | 20 |
| Successful routes | 20 (100%) |
| Sample trip weight | 454,883 |
| Successful trip weight coverage | 100% |
| Route distance | 44 m min／1,253 m median／51,151 m max |
| Segment count | 2 min／41 median／1,255 max |
| Maximum endpoint offset | 16.410 m |
| Endpoint offset bins | 40 `<=25m`; zero in all larger bins |
| Routes with repeated directed segment | 0 |
| Self-loop case | `self_loop_not_routed` as specified |

Rerun status, distance and canonical route hash were identical for all 20 routes. The reciprocal pair was requested independently; its directed route identity differs by construction and no reverse-path assumption was used. Machine-readable per-route coordinates and outcomes are in [`brouter-bounded-results.json`](brouter-bounded-results.json).

The QA figure plots four preselected successful routes with start/end markers: [`brouter_bounded_routes.png`](../reports/figures/brouter_bounded_routes.png). It is a geometry sanity check, not a publication map.

## Required unblock validation

Observed local runtime was 0.050 s median and 0.296 s p90 per route. A single-worker extrapolation for 1,124,015 non-self pairs is roughly 15.8 hours at the sample median or 92.3 hours at sample p90; median raw GeoJSON size implies about 6.03 GiB before cache/container overhead. This is an engineering estimate from 20 heterogeneous routes, not a service-level guarantee.

The BRouter environment and bounded execution pass, but 31 coordinate conflicts and 1,367 current-only coordinates remain a full-routing blocker. Do not begin the full job merely because this sample passes.
