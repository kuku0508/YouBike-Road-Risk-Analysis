# Phase 8.0A｜Historical coordinate coverage

## Node and flow coverage

| Coverage basis | Ready | Denominator | Coverage |
| --- | ---: | ---: | ---: |
| Tier 1 direct historical | 0 nodes | 2,782 | 0% |
| Tier 1 + Tier 2 accepted | 5 nodes | 2,782 | 0.1797% |
| Accepted endpoints on non-self OD | 0 edges | 1,124,015 | 0% |
| Accepted endpoints by trip weight | 0 trips | 85,115,195 | 0% |

5 個 Tier 2 stations 沒有彼此相連的 non-self OD，因此 node coverage 不能替代 edge／trip-weight coverage。

## Taipei / New Taipei

| City | Core nodes | Accepted | Unresolved | Key gap |
| --- | ---: | ---: | ---: | --- |
| Taipei | 1,506 | 5 | 1,501 | 1,375 pre-snapshot observations、4 single snapshot、31 conflicts、91 current-only |
| New Taipei | 1,276 | 0 | 1,276 | 全部 current-only；2024 snapshot 本來就是 Taipei-only |

Phase 8.0 的 1,367 current-only nodes 沒有新增 historical support：1,276 New Taipei、91 Taipei。這是 evidence source coverage gap，不是 station validity 判決。

## Highest-impact unresolved stations

依 individual station 觸及的 non-self trip weight 排序，前五個 ID 為 `500101022`（1,696,987）、`500101181`（995,000）、`500101001`（912,922）、`500107024`（779,380）、`500104108`（762,125）。這只是人工查證優先序；不會讓高流量站使用較弱證據。Individual impacts 彼此重疊，不能相加當成 unresolved union。

完整 priority table 保存在 `routing_coordinate_unresolved.parquet`，包含 station ID、candidate coordinate、unresolved reason、affected edge count、trip weight 與 counterpart count；未默默丟棄任何站。

## Readiness consequence

目前沒有可接受的 within-period relocation evidence，所以 coordinate-era count = 0；也因證據不足，不能斷言 era routing 永遠不需要。Full routing 必須等 dated official evidence 覆蓋全部 routing-relevant station periods，或每個日期能唯一對應到 non-overlapping coordinate era。

## Phase 8.0B coverage update

Legacy exact identity可接回2,769 nodes，且2,743有完整月份supporting rows；但provenance gate使routing-accepted nodes仍為5。New Taipei current-only 1,276站中1,267可identity-map、1,262具完整supporting timeline，routing-resolved仍為0。Node／OD-edge／trip-weight coverage均不因supporting evidence自動提高。
