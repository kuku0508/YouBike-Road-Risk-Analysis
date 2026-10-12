# Phase 5.0｜Core 2023–2024 SNA metrics

## Scope and contract

- **Report-specified**：原報告以2023/01–2024/12為核心網絡期間，列出Weighted Degree、Betweenness、Eigenvector、PageRank與Clustering公式；多數實作細節未保存。
- **Reconstruction decision**：本次只讀取`network-metric-contract-v1`，使用NetworkX 3.4.2、station ID節點與origin→destination有向邊。輸入固定為Phase 4.1 core OD，不含2025/01–03。
- **Primary result**：2,782 nodes、1,125,519 directed edges、91,138,763 trips；所有節點各一列，19欄均無NaN或Inf。完整表位於本機忽略檔`data/processed/network/core_2023_2024/node_metrics.parquet`。

## Primary definitions and validation

| Metric | Executed definition | Self-loop | Validation |
| --- | --- | --- | --- |
| in/out/total strength | `trip_count` flow；borrow=out、return=in | in與out各計一次 | sums = 91,138,763／91,138,763／182,277,526 |
| Betweenness | directed、unweighted、exact、normalized、endpoints=false | excluded | finite且落在[0,1] |
| Eigenvector | directed unweighted left／predecessor，max_iter=1000，tol=1e-9 | excluded | 收斂；Euclidean norm=1（容許差1e-6） |
| PageRank | directed weighted，alpha=.85，uniform personalization／dangling，tol=1e-9 | retained | sum=1（容許差1e-8） |
| Clustering | undirected simple unweighted projection | excluded | finite且落在[0,1] |

原報告把借／還方向文字寫成in／out，與O→D圖方向相反。本重建依圖契約固定為借車起點=`out_strength`、還車終點=`in_strength`，沒有沿用文字錯置。

## Deterministic primary rankings

完整Top 20見[`sna-primary-rankings.csv`](sna-primary-rankings.csv)；排序規則固定為metric降冪，再以station ID升冪處理同分。以下只列各指標第一名，描述限於「依該指標最高」。

| Metric | Station ID | Station | Value |
| --- | --- | --- | ---: |
| in-strength | 500101022 | 捷運公館站(2號出口) | 884,752 |
| out-strength | 500101022 | 捷運公館站(2號出口) | 838,271 |
| total-strength | 500101022 | 捷運公館站(2號出口) | 1,723,023 |
| betweenness | 500103044 | 大龍峒公園 | 0.01057831 |
| eigenvector | 500103044 | 大龍峒公園 | 0.04456741 |
| PageRank | 500101022 | 捷運公館站(2號出口) | 0.005238357 |
| clustering | 500104109 | 華聲公園(環河北路二段280巷口) | 1.0 |

Clustering有大量同為1的站點；第一名只是既定tie-break的結果，不代表它比其他同分站更高。

## Report comparison

- **Broadly consistent**：原報告描述平日台大／公館借用量常居高；本次全期間strength結果亦由捷運公館站(2號出口)居首。但日型態與全期間aggregation不同，不能視為exact match。
- **Cannot verify**：原報告沒有留下可逐站重算的完整centrality表、套件版本與全部參數；因此Betweenness、Eigenvector、PageRank及Clustering排名無法判定exact match。沒有為追求相似排名而改動contract。

## Reproducibility and boundaries

- 執行器：`src/run_core_sna_metrics.py`；machine-readable receipt：[`sna-metrics-receipt.json`](sna-metrics-receipt.json)。
- 三個Betweenness均為exact computation，未使用sampling approximation；每項checkpoint綁定contract hash、core OD hash與NetworkX版本。
- Node Parquet SHA-256為`a31ade358f59529ca8d5784bd0151aa17be6894b3a39194322534659dd27fe72`，大小292,449 bytes；不納入Git。
- 本階段未執行Louvain、modularity、K-means、hierarchical clustering、routing或事故matching。

**狀態：CORE SNA METRICS: COMPLETE**
