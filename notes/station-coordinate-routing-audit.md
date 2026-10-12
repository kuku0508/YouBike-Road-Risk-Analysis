# Phase 8.0｜Station-coordinate routing audit

## Results

| Status | Nodes | Routing treatment |
| --- | ---: | --- |
| Unique coordinate in dated 2024-05-31 snapshot | 1,384 | Primary coordinate candidate |
| Coordinate differs between 2024 and 2026 snapshots | 31 | Fail closed: `coordinate_conflict` |
| Only current 2026 metadata available | 1,367 | Coordinate exists, historical validity unresolved |
| Missing from all inspected metadata | 0 | None observed |
| Outside broad expected bounds | 0 | None observed |
| Exact duplicate coordinate groups across IDs | 0 | None observed at 7 decimals |

All 2,782 canonical IDs have at least one observed coordinate, but “has a current coordinate” is not equivalent to “has a historically valid 2023–2024 routing coordinate.” Therefore station-coordinate readiness is not complete: 31 IDs conflict and 1,367 rely only on later current snapshots.

The 31 conflict IDs touch 43,979 non-self OD edges and 3,805,894 non-self trips. The 1,367 current-only IDs touch 243,665 non-self edges and 2,789,522 non-self trips. These sets overlap: their union is 282,286 non-self edges and 6,541,800 trips, so individual counts must not be added. Relative to the non-self routing universe, the unresolved union is 25.11% of edges and 7.69% of trip weight.

The 31 conflicting IDs are retained machine-readably in [`brouter-contract-validation.json`](brouter-contract-validation.json). This phase does not average coordinates, choose the newest value, merge IDs or geocode names.

Sources:

- 2024-05-31 preserved Taipei snapshot, SHA-256 `c696c0f23f55cef97862c324468781d85b752bd5f9557e3608e691f9c930634a`.
- 2026-09-13 current Taipei snapshot, SHA-256 `0ac45607a811c3d7dde8727f2d1d4e005dcece367b1411c211eabfa2496f6969`.
- 2026-09-14 current New Taipei snapshot, SHA-256 `325d0adc6b89ee986fd8abf1cd453d67ba645cd70432c92404436aa991578d27`.

The audit preserves source date and city but cannot infer an unobserved move date from two snapshots.

## Phase 8.0A follow-up

The temporal audit reproduced the initial counts, then evaluated evidence against each station's first/last core-month observation. Only 5 stations are Tier 2 temporally bracketed and none form a non-self OD with another accepted station. The remaining 2,777 are preserved as unresolved; all 31 conflicts remain unresolved. See [`historical-coordinate-resolution.md`](historical-coordinate-resolution.md) and the immutable receipt for the stricter result.
