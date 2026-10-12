# Phase 8.4B — 事故至 BRouter 流量微路段正式配對

## 結論

Phase 8.4B 首次建立正式、可重現的 `accident → direction-neutral BRouter physical microsegment` 配對。Canonical dataset 保留全部 46,586 件事故；10 m primary policy 成功配對 39,711 件（85.2423%）。本階段沒有計算 accidents/exposure、EPDO、CBI、風險分數或 hotspot。

## 正式政策

- **Analytical decision：**primary point-to-LineString distance threshold 為 10.0 m；這不是官方標準，也不代表真實定位誤差恰為10 m。
- `contained_valid_road`與`contained_blank_road_id`只使用 Phase 8.4A 的 polygon-constrained candidate space；context-empty 不退回 global。
- `outside_reference_coverage`只使用 global direction-neutral candidate space，並保留原 road-context status。
- Exact minimum tie 在10 m內為`ambiguous_exact_tie`，不選winner；距離>10 m時距離規則優先。
- Near tie不排除唯一最近候選，只保留gap診斷。
- 只有空間配對凍結後才join exposure；流量不參與候選排序或tie處理。

## Primary 10 m結果

| 狀態 | N | 全部事故占比 |
|---|---:|---:|
| matched_context | 34,460 | 73.9707% |
| matched_global | 5,251 | 11.2716% |
| context_no_brouter_candidate | 1,241 | 2.6639% |
| unmatched_distance | 5,443 | 11.6838% |
| ambiguous_exact_tie | 190 | 0.4078% |
| coordinate_unavailable | 1 | 0.0021% |
| contained_multiple_unresolved | 0 | 0% |

七種狀態精確合計46,586。只有`matched_context`與`matched_global`具有assigned key與exposure；其餘assigned/exposure欄位皆為null。

## Road-context分層品質

| Road context | N | Matched | Match rate | Ambiguous | Distance-unmatched | No candidate |
|---|---:|---:|---:|---:|---:|---:|
| contained_valid_road | 37,859 | 34,435 | 90.9559% | 159 | 2,024 | 1,241 |
| contained_blank_road_id | 25 | 25 | 100% | 0 | 0 | 0 |
| outside_reference_coverage | 8,701 | 5,251 | 60.3494% | 31 | 3,419 | 0 |
| coordinate_unavailable | 1 | 0 | 0% | 0 | 0 | 0 |

Outside-reference match rate明顯較低，與Phase 8.4A觀察到的較長global distance尾端一致；這是道路reference與BRouter coverage限制，不代表該群事故無效。

## Threshold sensitivity

| Threshold | Matched | Match rate | Ambiguous | Distance-unmatched |
|---|---:|---:|---:|---:|
| 5 m | 34,106 | 73.2108% | 107 | 11,131 |
| **10 m primary** | **39,711** | **85.2423%** | **190** | **5,443** |
| 20 m | 41,926 | 89.9970% | 284 | 3,134 |

5 m與20 m只作敏感度證據，不產生其他canonical datasets。

Primary matched accidents中，second-minus-first gap ≤0.1/0.5/1 m分別為3,929（9.8940%）、8,861（22.3137%）、13,094（32.9732%）。這些near ties不改變primary status。

## Direction-neutral exposure

106,049個physical segments全部建立exposure row：62,864個為one-direction-only BRouter output，43,185個具有正反方向members。One-direction-only不代表真實道路必然是單行道。

Exact integer conservation：

- Total：4,674,227,848
- Weekday：3,307,530,105
- Holiday：1,366,697,743
- Weekday + holiday = total：通過

所有matched segments的total exposure皆>0；weekday／holiday可為0但無負值。事故沒有可靠方向資訊，因此後續若使用exposure，正式單位是direction-neutral member-flow sum。

## Artifacts與驗證

- Canonical matching：`data/processed/accidents/accident_brouter_segment_matches_2023_2024.parquet`
- Direction-neutral exposure：`data/processed/routing/direction_neutral_segment_exposure_2023_2024.parquet`
- Matching fingerprint：`db598989c4b0278fdec77d35b7fb9ef10c5d139ba267e5f67f7620c72d687658`
- Matching Parquet SHA-256：`bdad7b3190f27991c15dd5860a9792b41ca7a545352e1b37ec2e59361a2e2baf`
- Exposure fingerprint：`d494a2ddc33e76dc169454af08996ae91543bea6a540a06832d3ede9d4cfad88`
- Exposure Parquet SHA-256：`c6dd301a7b328d650aa4e58a7e9b36330d6389465594ad69010d39c02dd0cd6f`

大型Parquet均Git ignored。ID set、assigned segment foreign key、one-to-one exposure join、null policy、status與exposure conservation均通過。

## Readiness與限制

狀態：**PHASE 8.5 READY FOR SEPARATELY AUTHORIZED RISK CONTRACT**。

這只代表正式matching與denominator input已驗證。下一階段仍須明確定義severity、EPDO／CBI、exposure denominator、低流量穩定性、零值與排名呈現方式；不得把BRouter模擬flow描述成GPS實測流量，也不得把配對結果解讀成因果風險。
