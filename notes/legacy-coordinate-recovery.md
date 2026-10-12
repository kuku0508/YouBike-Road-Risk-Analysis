# Phase 8.0B｜Legacy historical coordinate recovery

## Status

**LEGACY HISTORICAL COORDINATES: NOT SUFFICIENTLY TRACEABLE**

Identity mapping成功率高，但來源與month semantics無法追溯，且coordinate timeline顯示疑似靜態座標回填。因此legacy evidence已append為`supporting_not_routing_accepted`，不改變Phase 8.0A routing readiness。

## Reproduced profile

| Measure | Result |
| --- | ---: |
| Full rows | 64,413 |
| Available months | 2023/01–2025/03，27 months |
| Core rows | 56,408 |
| Core rows with both coordinates | 54,913 |
| Core rows missing either coordinate | 1,495 |
| One-coordinate-only rows | 0 |
| Core unique raw station names | 3,015 |
| Distinct valid name-coordinate histories | 2,902 |

Prompt中的約數均重現；另確認缺座標是雙欄一起缺失，不是單側coordinate。

## Coordinate timelines

2,769個identity-mapped IDs全部為`stable_exact_coordinate`；2,743個在每個routing-relevant trip month都有一筆有效legacy coordinate。這是強 supporting consistency，但不是官方historical validity，因為完全不變的模式也可能來自事後static lookup。

沒有confirmed within-period relocation；coordinate-era count為0。這不代表真實 relocation 不存在，而是此來源不能可靠偵測。Routing contract維持`road-routing-contract-v1`，不升v2。

## Existing blockers

### 31 coordinate conflicts

- 31/31 identity mapped
- 28/31 routing-relevant months完整
- 8 legacy coordinates等於2024 snapshot
- 20等於2026 snapshot
- 3兩邊皆不等
- Routing-resolved：0

即使8站支持2024位置跨越其routing months，仍不能用未確認provenance突破gate；20站把2026位置呈現在2023–2024月份，反而顯示month不是coordinate validity的可靠證據。

### 1,367 current-only nodes

| City | Current-only | Identity mapped | Temporally complete supporting rows | Routing-resolved |
| --- | ---: | ---: | ---: | ---: |
| Taipei | 91 | 91 | 90 | 0 |
| New Taipei | 1,276 | 1,267 | 1,262 | 0 |
| Total | 1,367 | 1,358 | 1,352 | 0 |

這份CSV確實大量包含New Taipei station names與coordinates，但無法證明座標在各月份當時有效。

## Before / after readiness

| Measure | Phase 8.0A before | Phase 8.0B after |
| --- | ---: | ---: |
| Routing-ready nodes | 5 / 2,782 | 5 / 2,782 |
| Routable non-self OD edges | 0 / 1,124,015 | 0 / 1,124,015 |
| Routable trip weight | 0 / 85,115,195 | 0 / 85,115,195 |

Final accepted coordinate artifact維持5 rows且hash不變。沒有執行full routing。

## Artifacts

- `data/interim/routing/legacy_station_name_mapping.parquet`
- `data/interim/routing/legacy_coordinate_evidence.parquet`
- `data/interim/routing/legacy_station_name_anomalies.parquet`
- `data/interim/routing/legacy_coordinate_timeline.parquet`
- `data/interim/routing/legacy_phase8a_conflict_timeline.parquet`
- appended `data/interim/routing/station_coordinate_evidence.parquet`

所有大型artifacts由`.gitignore`排除；rows與SHA-256見[`legacy-coordinate-recovery-receipt.json`](legacy-coordinate-recovery-receipt.json)。整合是idempotent：同一legacy source重跑會replace既有append rows，不會累積duplicate evidence。
