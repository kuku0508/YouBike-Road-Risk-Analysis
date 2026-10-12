# Phase 7.1｜Full-core K-means results

## Executive summary

- **Elbow diagnostic**：完整2,782 nodes、StandardScaler與固定KMeans參數下，deterministic knee為**k=3**，不是原報告的k=4。
- **Secondary diagnostic**：silhouette最高為**k=2（0.561518）**；k=4為0.509820。Silhouette不是原報告指定的選群方法。
- **Report-reference clustering**：仍依契約執行正式k=4；四群為60、347、939及1,436 nodes，全數且只被指派一次。
- Primary fixed-seed重跑的assignment、centroid與inertia一致。Seed sensitivity只有1個邊界node改群；scaling sensitivity則顯示membership對尺度選擇有實質敏感性。

## Scope and evidence labels

- **Report-specified**：報告p.23以Weighted Degree、Betweenness、Clustering與PageRank進行K-means，elbow圖涵蓋k=1–10並採k=4。
- **Reconstruction decision**：依`kmeans-reconstruction-contract-v1`使用`total_strength`、`betweenness_primary`、`clustering_primary`、`pagerank_primary`，以StandardScaler及明確固定的scikit-learn參數重建。
- **Elbow diagnostic**：本次最大normalized point-to-chord distance出現在k=3。
- **Report-reference k=4 result**：不論本次diagnostic是否支持4，仍執行k=4供報告對照；不得稱為本次最佳k。

Input是Phase 5 core 2023–2024 node metrics，SHA-256為`a31ade358f59529ca8d5784bd0151aa17be6894b3a39194322534659dd27fe72`。2,782個`station_id`完整且唯一，四features均finite，沒有imputation、outlier removal或feature leakage。

## Full-core elbow and silhouette

| k | Inertia / WCSS | Iterations | Distance to chord | Silhouette |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 11,128.000 | 2 | 0.000000 | — |
| 2 | 6,346.655 | 6 | 0.261727 | 0.561518 |
| 3 | 4,307.087 | 6 | **0.328318** | 0.530705 |
| 4 | 3,518.353 | 10 | 0.305886 | 0.509820 |
| 5 | 2,877.284 | 10 | 0.272944 | 0.510144 |
| 6 | 2,256.564 | 7 | 0.238554 | 0.531690 |
| 7 | 1,851.722 | 7 | 0.188800 | 0.532201 |
| 8 | 1,522.395 | 11 | 0.133671 | 0.509896 |
| 9 | 1,341.426 | 13 | 0.067983 | 0.464857 |
| 10 | 1,192.713 | 10 | 0.000000 | 0.467727 |

完整normalized curve、runtime與distance保存在[`kmeans-elbow.csv`](kmeans-elbow.csv)。Deterministic knee=k=3；silhouette-best k=2。兩者與原報告k=4不同，因此k-selection comparison分類為**materially different**。這不等於k=4結果無效，而是表示本次明確契約下，k=4不是兩項diagnostic的最佳值。

## Report-reference k=4 result

Primary inertia=3,518.353045，silhouette=0.509820。Cluster IDs依群內最小station ID升冪重新編為1–4，只是識別碼，沒有強弱或功能順序語意。

| Cluster | Nodes | Proportion | Descriptive feature pattern |
| ---: | ---: | ---: | --- |
| 1 | 60 | 2.16% | 四項centrality／flow皆高、clustering低 |
| 2 | 347 | 12.47% | flow、PageRank與betweenness偏高、clustering偏低 |
| 3 | 939 | 33.75% | flow與PageRank接近整體平均、clustering低於平均 |
| 4 | 1,436 | 51.62% | flow與centrality低、clustering高 |

Size distribution：min=60、median=643、mean=695.5、max=1,436。群大小明顯不平衡，但依contract只描述、不改k。

### Scaled centroids

| Cluster | z-strength | z-betweenness | z-clustering | z-PageRank |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 4.016731 | 3.942739 | -1.672813 | 4.076814 |
| 2 | 1.474509 | 0.921485 | -1.007633 | 1.413475 |
| 3 | 0.049622 | 0.008327 | -0.672260 | 0.130862 |
| 4 | -0.557998 | -0.393770 | 0.754200 | -0.598870 |

### Original-scale centroids and robust profile

括號內為P25／median／P75；完整欄位保存在[`kmeans-cluster-summary.csv`](kmeans-cluster-summary.csv)。

| Cluster | Total strength | Betweenness | Clustering | PageRank |
| ---: | --- | --- | --- | --- |
| 1 | 506,398（357,886／464,454／600,432） | 0.001568（0.000754／0.001114／0.001879） | 0.437943（0.385219／0.451926／0.487200） | 0.002006（0.001525／0.001795／0.002273） |
| 2 | 227,363（170,100／210,411／271,724） | 0.000478（0.000292／0.000407／0.000575） | 0.550734（0.511404／0.555119／0.596173） | 0.000930（0.000719／0.000862／0.001091） |
| 3 | 70,967（37,364／70,410／99,487） | 0.000149（0.000063／0.000113／0.000203） | 0.607601（0.590449／0.638766／0.677063） | 0.000412（0.000306／0.000406／0.000520） |
| 4 | 4,274（63／368／2,011） | 0.00000357（0／0／0） | 0.849478（0.802401／0.849374／0.892663） | 0.00011758（0.00009553／0.00009820／0.00011111） |

`total_strength`與`pagerank_primary`的Pearson correlation為0.951308，因此「高flow＋高PageRank」不能當作兩份完全獨立的證據。四features仍全部保留，因為原報告明列這四項。

## Representative stations

「Prototype」是scaled feature space中距離該群centroid最近的站，不代表最重要站。

| Cluster | Highest strength | Highest betweenness | Highest clustering | Highest PageRank | Prototype |
| ---: | --- | --- | --- | --- | --- |
| 1 | 捷運公館站(2號出口) | 大稻埕碼頭 | 臺灣科技大學後門 | 捷運公館站(2號出口) | 林森長春路口 |
| 2 | 臺大第一活動中心西南側 | 汀州思源街口東南側 | 泰和公園 | 捷運內湖站(1號出口) | 捷運松江南京站(8號出口) |
| 3 | 臺大男八舍東側 | 福安消防分隊 | 臺大五號館西側 | 湖光國宅 | 福林公園(福林路) |
| 4 | 臺大共同教室北側 | 古風公園 | 銘傳大學(中山北路五段280巷口) | 內湖路三段326巷口 | 保平路214巷 |

## Comparison with the report

| Item | Report | Reconstruction | Classification |
| --- | --- | --- | --- |
| Elbow selection | k=4 | deterministic knee k=3 | materially different |
| Silhouette selection | not specified | best k=2 | cannot compare method |
| Formal clustering | k=4 | report-reference k=4 | consistent in requested k only |
| Role Group 2 average flow | about 610k | closest high-flow centroid=506,398 | cannot verify equivalence |
| Role Group 1 average clustering | about 0.752 | cluster centroids=0.438–0.849 | cannot verify equivalence |
| Cluster sizes／assignments | not reported in auditable form | 60／347／939／1,436 | cannot verify |

原報告的Role Group labels沒有留下可核對的station assignment與完整centroid，因此不能把Role Group 1／2直接對應到本次Cluster 1／2。沒有為貼近報告而改scaling、seed或features。

## Reproducibility and outputs

- Primary seed 42重跑的assignment fingerprint、centroids及inertia一致。
- Assignment fingerprint：`bccae38d2937c71b5adfffb2a864035dc00cd331f0f43009668910a2ff93e971`。
- 2,782 nodes全數且只被指派一次；IDs連續1–4；raw／scaled join無錯位。
- 正式partition與summary Parquet已完整reread；大型產物留在本機並由Git忽略。
- Elbow runtime 4.34 s；primary k=4 0.11 s；完整流程6.55 s；peak working set約325.39 MiB。

**狀態：CORE K-MEANS: COMPLETE**
