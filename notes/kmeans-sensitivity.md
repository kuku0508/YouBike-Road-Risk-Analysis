# Phase 7.1｜K-means sensitivity analysis

## Seed sensitivity

Primary使用StandardScaler與k=4；除seed外所有KMeans參數完全相同。ARI／NMI比較membership，不直接比較raw labels。

| Seed | Inertia | Silhouette | Cluster sizes | ARI vs primary | NMI vs primary |
| ---: | ---: | ---: | --- | ---: | ---: |
| 42 | 3,518.353045 | 0.509820 | 60／347／939／1,436 | 1.000000 | 1.000000 |
| 7 | 3,518.336400 | 0.509892 | 60／346／940／1,436 | 0.999306 | 0.997485 |
| 19 | 3,518.332954 | 0.509892 | 60／346／940／1,436 | 0.999306 | 0.997485 |
| 73 | 3,518.353045 | 0.509820 | 60／347／939／1,436 | 1.000000 | 1.000000 |

- **Objective stability**：inertia差異小於0.021，十分接近。
- **Cluster-size stability**：seed 7／19相較primary只有Cluster 2與3各差1個node。
- **Membership stability**：seed 7／19並非完全相同，ARI=0.999306、NMI=0.997485；不能只憑inertia接近宣稱partition完全一致。Seed 73與primary完全一致。

## Scaling sensitivity

各variant皆使用k=4、seed=42及相同KMeans參數。不同feature space的inertia不可直接比較模型優劣。

| Scaling | Inertia | Silhouette | Cluster sizes | ARI vs primary | NMI vs primary |
| --- | ---: | ---: | --- | ---: | ---: |
| StandardScaler primary | 3,518.353 | 0.509820 | 60／347／939／1,436 | 1.000000 | 1.000000 |
| None | 4.247e12 | 0.718344 | 32／226／683／1,841 | 0.515937 | 0.535870 |
| MinMaxScaler | 23.0300 | 0.552987 | 292／1,109／1,339／42 | 0.754273 | 0.691604 |
| log1p(strength)＋StandardScaler | 3,518.384 | 0.550089 | 186／1,260／1,291／45 | 0.646477 | 0.615614 |

**Observed sensitivity**：partition對scaling有實質敏感性。No scaling由`total_strength`量級主導；MinMax與log-strength也改變membership及群大小。這些結果支持保留StandardScaler作明確的primary reconstruction decision，也提醒後續解讀不能把四群視為對所有合理preprocessing都穩定的自然類別。

Silhouette在不同scaling space之間也不是無條件可比的同一幾何問題；本表只記錄各variant內部diagnostic，不用來取代primary contract。

完整machine-readable結果見[`kmeans-sensitivity-summary.json`](kmeans-sensitivity-summary.json)。本階段沒有執行hierarchical clustering。
