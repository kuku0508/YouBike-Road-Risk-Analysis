# Phase 7.0｜K-means Reconstruction Contract

## Report evidence

- **Report-specified**：報告p.23明列Weighted Degree、Betweenness Centrality、Clustering Coefficient與PageRank四項K-means變數；圖13顯示elbow curve的k=1–10，文字宣稱k=4為轉折點並據此採四群。
- **Report-implied**：p.24將`Avg_Flow`稱為平均借還規模，p.25以群平均流量呈現結果；這支持整體借還量語意，但沒有明確說Weighted Degree究竟是total、in或out。
- **Implementation unspecified in report**：standardization／normalization、log transform、outlier handling、distance preprocessing、library、init、`n_init`、seed、max_iter、tol、algorithm與自動knee判定均未記錄。
- PDF p.23–25已重新做文字與頁面影像核對；原件為`references/資料探勘第一組.pdf`。

## Final primary feature contract

| Feature | Source | Semantics |
| --- | --- | --- |
| `total_strength` | Phase 5 primary | in＋out flow；self-loop在in/out各計一次，total計兩次 |
| `betweenness_primary` | Phase 5 primary | directed、unweighted、normalized、self-loop excluded |
| `clustering_primary` | Phase 5 primary | undirected simple unweighted projection、self-loop excluded |
| `pagerank_primary` | Phase 5 primary | directed、`trip_count` weighted、alpha=.85、self-loop retained |

**Reconstruction decision**：Weighted Degree採`total_strength`，因它最接近報告的整體加權度及「平均借還規模」；不能寫成原報告明確指定total。Louvain community ID、座標、city／district、bike type及所有其他欄位均不得進入feature matrix。

## Full feature audit（未fit K-means）

2,782個station IDs完整且唯一；四欄皆無NaN或Inf。

| Feature | Min | Median | Mean | P95 | P99 | Max | Skewness |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| total_strength | 1 | 16,525 | 65,520.32 | 274,642.25 | 487,159.38 | 1,723,023 | 3.74495 |
| betweenness_primary | 0 | 0.00001708 | 0.00014565 | 0.00062012 | 0.00144808 | 0.01057831 | 11.72116 |
| clustering_primary | 0 | 0.733406 | 0.721592 | 0.949782 | 1 | 1 | -1.15712 |
| pagerank_primary | 0.00009500 | 0.00018873 | 0.00035945 | 0.00110754 | 0.00200062 | 0.00523836 | 3.22616 |

完整min、max、mean、median、sample std、P1／P5／P25／P75／P95／P99與skewness保存在[`kmeans-contract-validation.json`](kmeans-contract-validation.json)。Raw range中`total_strength`與`clustering`相差1,723,022倍；若直接使用raw Euclidean distance，flow magnitude會壓過其他metrics。

Pearson顯示`total_strength`與PageRank為0.9513；Spearman為0.9885。四特徵有高度冗餘，但因它們是報告明列分析集合，本階段不自行刪除。

## Preprocessing and outlier policy

Primary採scikit-learn `StandardScaler(with_mean=True, with_std=True)`：

\[
z_{ij}=\frac{x_{ij}-\mu_j}{\sigma_j}
\]

這是**Reconstruction decision**，不是report-specified。完整特徵矩陣驗證transform後每欄population mean≈0、variance≈1，inverse transform回原值。

- Primary不做log transform。
- 不做imputation；任何NaN／Inf、重複或缺失station ID、row count不符皆fail closed。
- 不做outlier removal、winsorization或percentile trimming。高flow／centrality stations正是研究對象，不應因極端而消失。

## K-means implementation contract

| Parameter | Value |
| --- | --- |
| Library | scikit-learn 1.8.0 |
| Class | `sklearn.cluster.KMeans` |
| init | `k-means++` |
| n_init | 50（明確指定，不依版本預設） |
| max_iter | 300 |
| tol | 1e-4 |
| algorithm | `lloyd` |
| random_state | 42 |

上述未被報告指定的項目均為reconstruction decisions。`n_init=50`降低單次local optimum敏感度；固定seed使相同input與設定可重現。

## Elbow and secondary diagnostic contract

- Elbow k範圍固定為1–10，對應報告圖13可見橫軸。
- 每個k使用完全相同feature matrix、StandardScaler、init、`n_init`與seed，記錄inertia／WCSS。
- Human-readable輸出為inertia-vs-k curve。
- Deterministic diagnostic：先將k與inertia各自縮放至[0,1]，計算每一點到首尾端點連線的垂直距離；最大距離為knee，同距離時取最小k。
- 此幾何diagnostic是reconstruction工具，不宣稱為原報告實作。
- Silhouette只在k=2–10計算，作secondary diagnostic，不能取代報告的elbow方法。
- 報告k=4只作post-hoc reference，不是acceptance target；Phase 7.1若不支持4，也不得更換scaling或seed去配合。

## Labels, centroids and interpretation

- Raw KMeans labels沒有語意。正式partition依每群最小station ID升冪後重新編為1-based integer。
- Label只作識別碼，不代表重要程度、高低或好壞。
- Phase 7.1同時輸出scaled-space centroid與inverse-transformed original-unit centroid。
- 初始輸出只稱Cluster 1、Cluster 2…，並描述各feature高低；沒有額外證據前不得直接命名為核心、住宅、轉運或邊陲站。

## Sensitivity plan

- Scaling：raw／no scaling、MinMaxScaler。
- Distribution：`log1p(total_strength)`後StandardScaler；因total strength range大且skewness=3.74495，保留為有限sensitivity，不是primary。
- Seeds：7、19、73，與primary 42比較inertia及membership stability。
- k sensitivity：完整k=1–10 elbow；silhouette只評估2–10。

## Validation and hard stop

- 10-row synthetic matrix含四種不同尺度、清楚結構與極端值；scaling、inverse transform、fixed-seed determinism、`n_init=50`、inertia reproducibility、knee diagnostic、deterministic relabel與不刪outlier均通過。
- 12-row bounded real subset只驗證feature extraction、scaling與KMeans parameter plumbing；不解讀partition。
- Full 2,782-node data只執行feature profile與scaler transform／inverse transform，`full_core_kmeans_executed=false`。
- 本階段沒有正式k=4 clustering、cluster size、hierarchical clustering、routing或事故分析。

**狀態：Phase 7.0 contract finalized；正式full-core K-means尚未執行。**
