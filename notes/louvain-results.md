# Phase 6.1｜Core 2023–2024 Louvain results

## Scope and primary contract

- **Report result**：原報告約11個生活圈，正文Q約0.665，community contribution sum約0.66574；projection、self-loop、resolution、seed與library均未留下。
- **Reconstruction primary result**：依`louvain-reconstruction-contract-v1`，將core directed OD作sum projection，移除Louvain-layer self-loops，以NetworkX 3.4.2 weighted undirected Louvain、resolution=1.0、threshold=1e-7、seed=42執行。
- Primary graph重驗為2,782 nodes、748,591 undirected edges與85,115,195 projected weight；另有1,504條self-loop／6,023,568 trips移除於Louvain layer，兩者加總回91,138,763。

## Primary result

| Result | Value |
| --- | ---: |
| Community count | 8 |
| Modularity Q | 0.6344295412486247 |
| Independent contribution sum | 0.6344295412486246 |
| Absolute Q difference | 1.11e-16 |
| Nodes assigned | 2,782 / 2,782 |
| Singleton communities | 0 |

NetworkX modularity與獨立community decomposition在`1e-12`容許誤差內一致。Community IDs經每群最小station ID升冪重新編為1–8；每站恰好一列，無遺漏、重複或非連續ID。

## Community sizes and descriptive representatives

| Community | Nodes | Dominant city | Top by total strength | Top by PageRank | Top by betweenness |
| ---: | ---: | --- | --- | --- | --- |
| 1 | 303 | Taipei | 捷運公館站(2號出口) | 捷運公館站(2號出口) | 汀州思源街口東南側 |
| 2 | 210 | Taipei | 捷運六張犁站 | 捷運六張犁站 | 龍門廣場 |
| 3 | 493 | Taipei | 捷運中山國中站 | 捷運中山國中站 | 永樂市場 |
| 4 | 722 | New Taipei | 捷運龍山寺站(1號出口) | 捷運龍山寺站(1號出口) | 大稻埕碼頭 |
| 5 | 342 | Taipei | 捷運芝山站(2號出口)_1 | 捷運芝山站(2號出口)_1 | 關渡宮 |
| 6 | 209 | New Taipei | 捷運景美站(2號出口) | 捷運萬隆站(2號出口) | 捷運景美站(2號出口) |
| 7 | 224 | Taipei | 捷運劍南路站(2號出口) | 捷運劍南路站(2號出口) | 捷運劍南路站(2號出口) |
| 8 | 279 | Taipei | 捷運永春站(2號出口) | 松山車站 | 饒河疏散門(基四號疏散門) |

Size distribution：min=209、median=291、mean=347.75、max=722。這些只是在既定network metric下的descriptive representatives；沒有把community命名成商業區、住宅區或通勤圈。原報告雖稱生活圈，本重建現階段只稱network communities。

`dominant_city`是community內station count最多的city label，不代表該群所有mobility都位於該行政區。Community 4與6的New Taipei dominance尤其受來源只完整觀察Taipei origins、但包含New Taipei destinations的資料邊界影響。

## Flow and modularity grain

- `internal_trip_weight`：原始directed OD中兩端同community的trip weight，包含data-layer self-loop。
- `external_trip_weight`：origin在community、destination在外部的directed outgoing weight。
- `boundary_trip_weight`：跨community的incoming與outgoing directed weights合計。
- `internal_edge_count`與`external_edge_count`：同一定義下的directed OD key counts。
- `internal_projected_weight`、`projected_total_strength`及`modularity_contribution`：sum-projected、undirected且移除self-loop的modularity graph。

兩種grain分欄保存，不將directed mobility flow和undirected modularity weight混用。完整小型摘要見[`louvain-community-summary.csv`](louvain-community-summary.csv)。

## Comparison with the report

| Item | Report | Reconstruction | Classification |
| --- | ---: | ---: | --- |
| Communities | about 11 | 8 | materially different |
| Q | about 0.665 / contribution sum 0.66574 | 0.63442954 | broadly similar numerically |
| Contribution sum | 0.66574 | 0.63442954 | broadly similar numerically |

Q相差0.03131046。這只能表示在本重建契約下數值量級相近，不能宣稱exact reproduction：原研究的directed→undirected處理、reciprocal merge、self-loop、resolution、seed、library與清理／station identity都無法確認。本次沒有用報告結果調參。

## Reproducibility and outputs

- Primary seed 42完整重跑的partition fingerprint、community count、Q與deterministic labels全部一致。
- Partition fingerprint：`97cee4a36abcea66e1f827a664dc5b334858b67e55977c104d8caa15e87fe3a8`。
- Primary runtime 7.47 s；repeat 6.29 s；完整primary＋sensitivities流程134.99 s；peak working set約2.02 GiB。
- 大型station partition及community Parquet留在本機並由Git忽略；small summaries、receipt與文件納入Git。

**狀態：CORE LOUVAIN: COMPLETE**
