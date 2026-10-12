# Phase 7.4｜Hierarchical Clustering Results

## Outcome

**HIERARCHICAL RECONSTRUCTION: COMPLETE**

本結果是**2023–2024 Hierarchical reconstruction variant**。原報告文字記載2022–2024；本專案依分析者決策採核心network period 2023–2024，不能稱為原報告母體的完全重現。

## Primary execution

Weekday與holiday各自獨立fit `StandardScaler(with_mean=True, with_std=True)`，再以Euclidean distances與SciPy 1.17.1 `linkage(method="ward")`重建Ward.D2。沒有log、winsorization、outlier removal、imputation或station sampling。

| Day type | Input | Linkage shape | Linkage SHA-256 | Cophenetic correlation | Report-reference cut |
| --- | --- | --- | --- | ---: | ---: |
| Weekday | 2,782×72 | 2,781×4 | `53bd62b7e07c74e74129b912f3fe389654484a01bb850d7647741886088447d5` | 0.642493 | k=5 |
| Holiday | 2,782×72 | 2,781×4 | `701c1af921d04b712bc94f9f6799818555e76ea074c505feaec24a97d296c640` | 0.642285 | k=4 |

兩份linkage的distance皆finite且單調不減，final merge count皆為2,782。Ward.D2是原報告用語；SciPy Ward／Euclidean是本專案的executable reconstruction，不宣稱與未知版本R `hclust(method="ward.D2")` bit-for-bit identical。

## Report-reference partitions

### Weekday k=5

| Cluster | Nodes | Share | Prototype station |
| ---: | ---: | ---: | --- |
| 1 | 45 | 1.62% | `500112085` 捷運市政府站(3號出口) |
| 2 | 550 | 19.77% | `500110052` 南京東路五段59巷口 |
| 3 | 767 | 27.57% | `500111075` 成德立體停車場 |
| 4 | 1,419 | 51.01% | `500214027` 汐止火車站停車場 |
| 5 | 1 | 0.04% | `500103044` 大稻埕碼頭 |

Size statistics：min=1、median=550、mean=556.4、max=1,419。

### Holiday k=4

| Cluster | Nodes | Share | Prototype station |
| ---: | ---: | ---: | --- |
| 1 | 65 | 2.34% | `500113039` 中華桂林路口 |
| 2 | 537 | 19.30% | `500107033` 江寧公園 |
| 3 | 2,179 | 78.33% | `500111089` 向陽南港路口(西北側) |
| 4 | 1 | 0.04% | `500103044` 大稻埕碼頭 |

Size statistics：min=1、median=301、mean=695.5、max=2,179。Prototype是距離該群standardized 72維centroid最近的station，不代表「最重要站」。

## 24-hour profile summary

- Weekday Cluster 1與Holiday Cluster 1的平均Betweenness／Eigenvector在凌晨約02–05時相對較高；PageRank峰值較分散。
- Weekday Cluster 2的Eigenvector在12–14時較高、PageRank在08–10時較高；Holiday Cluster 2的Eigenvector在15–17時、PageRank在09–11時較高。
- Weekday Cluster 3的Eigenvector偏向17–21時；Holiday Cluster 3的Eigenvector偏向15–17時。兩群的絕對centrality低於前兩群。
- 最大群Weekday Cluster 4的平均centrality整體低，Eigenvector較集中於17–19時；Holiday Cluster 3扮演相近的「大群、較低平均centrality」描述角色，但不是一對一對應。
- 單站群`500103044`在平日與假日都形成獨立群，具有極端72維輪廓；依既定policy保留，不視為錯誤或移除候選。

以上僅為hourly pattern的客觀描述，不命名為通勤、住宅、商業或觀光型。完整mean／median／p25／p75見兩份summary CSV。

## Weekday versus holiday

同一2,782站、相同72-feature定義下，weekday k=5與holiday k=4的exploratory comparison為：ARI=0.381598、NMI=0.456015。群數不同且不應期待一對一對應；cross-tab保存在machine-readable receipt。

## Report comparison

- 群數：Weekday 5、Holiday 4，與附錄顯示群數**exact**。
- 方法名稱：Euclidean＋Ward.D2與報告文字一致；實作環境等價性只能標記**cannot verify**。
- Branch structure／station membership：原報告沒有提供可稽核的完整linkage、leaf order或assignment，加上期間不同，標記**cannot verify**。
- Period caveat：原報告文字為2022–2024，本重建為分析者選定的2023–2024 variant。

## Reproducibility and artifacts

Weekday與holiday均重算一次；linkage、leaf order、assignment label hashes完全一致。完整linkage `.npy`、leaf-order JSON與partition Parquet保留於Git忽略的processed目錄。正式圖：

- [`hierarchical_weekday_dendrogram.png`](../reports/figures/hierarchical_weekday_dendrogram.png)
- [`hierarchical_holiday_dendrogram.png`](../reports/figures/hierarchical_holiday_dendrogram.png)

Machine-readable證據見[`hierarchical-run-receipt.json`](hierarchical-run-receipt.json)。
