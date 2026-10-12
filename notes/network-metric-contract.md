# Phase 4.2 — Network Metric Contract

Machine-readable contract：[`config/network_metric_contract.yaml`](../config/network_metric_contract.yaml)。內容使用JSON-compatible YAML，Phase 5必須讀取它，不得在分析程式散落hard-coded choices。

## Report evidence boundary

- **Report-specified**：R p.12列weighted total／in／out公式；p.13列shortest-path betweenness公式；p.14的Eigenvector公式把adjacency寫成0/1；p.14–15 PageRank寫`d=0.85`、incoming-link邏輯、依來源站不同目的地數分攤及dangling redistribution；p.15列`2E/[k(k-1)]` clustering公式。
- **Report-implied**：報告整體稱YouBike network為directed weighted；PageRank文字提流量，但公式分母是目的地數而非weighted out-strength。
- **Implementation unspecified**：Betweenness是否weighted及distance transform、Eigenvector left/right與weight、PageRank是否使用trip count、Clustering directed／weighted／local implementation、所有metrics的self-loop handling與實際函式庫設定。
- **Reconstruction decision**：以下primary choices均為可重現重建，不冒充原研究當時實作。

## Metric decision table

| Metric | Direction | Weight | Self-loop | Primary semantics |
|---|---|---|---|---|
| Weighted Degree | directed in／out／total | `trip_count` strength | include | out=借出、in=歸還、total=in+out |
| Betweenness | directed | unweighted | exclude | normalized shortest-path betweenness、endpoints=false |
| Eigenvector | directed left | unweighted | exclude | predecessor／incoming influence |
| PageRank | directed O→D | `trip_count` transition strength | include | alpha=.85、uniform personalization／dangling |
| Clustering | undirected simple projection | unweighted | exclude | local `2E/[k(k-1)]` |

## Weighted Degree

\[
s_i^{out}=\sum_jw_{ij},\qquad s_i^{in}=\sum_jw_{ji},\qquad
s_i^{total}=s_i^{in}+s_i^{out}.
\]

- **Report-specified**：總加權度為in與out相加；報告也分列兩者公式。
- **Report inconsistency**：報告文字把借車稱in、還車稱out，與origin→destination相反。
- **Reconstruction decision**：借出為out、歸還為in，並同時輸出三欄。沒有normalization。
- Self-loop `i→i`在in與out各貢獻`w_ii`，所以total貢獻`2w_ii`。Synthetic node D驗證為in=9、out=6、total=15，其中loop weight=5。
- Sensitivity：另設exclude-loop版本，但不取代primary。

## Betweenness Centrality

- **Report-specified**：最短路徑介數公式。
- **Implementation unspecified**：是否weighted、directed mode、normalization、endpoints與flow-to-distance轉換。
- **Primary reconstruction**：directed、unweighted、normalized=`True`、endpoints=`False`、移除self-loops。
- 理由：`trip_count`越大表示關係越強，但NetworkX weighted shortest path把數值解讀成distance；直接使用`trip_count`會讓高流量邊看似更遠。
- Sensitivity A：`distance=1/trip_count`。
- Sensitivity B：`distance=1/log(1+trip_count)`。
- Synthetic A→B：unweighted選直接`A→B`；inverse-flow選高流量的`A→C→B`，證明transform會實質改變最短路徑與betweenness。

## Eigenvector Centrality

- **Report-specified**：adjacency為0/1；公式未釐清矩陣方向。
- **Primary reconstruction**：directed unweighted、NetworkX left dominant eigenvector，分數由predecessors／incoming neighbors累加；self-loop排除；unit Euclidean norm；`max_iter=1000, tol=1e-9`。
- **Implementation unspecified**：原研究用left或right eigenvector、是否weighted、是否保留loop。
- Synthetic graph的left與reverse/right結果不同，確認函式名本身不足以判斷方向。
- Sensitivity：weighted left with `trip_count`；unweighted right semantics以reversed graph計算。

## PageRank

- **Report-specified**：origin→destination incoming-link語意、`d/alpha=0.85`、uniform random restart與dangling influence平均分配。
- **Implementation unspecified**：原實作是否以flow加權；公式描述以目的地數分攤，文字又稱反映流量。
- **Primary reconstruction**：directed weighted PageRank，`weight=trip_count`、`alpha=0.85`、uniform personalization、dangling沿uniform personalization、self-loop保留、`max_iter=1000, tol=1e-9`。
- `trip_count`在此是transition preference，不是distance。Synthetic weighted與unweighted結果不同，weighted scores總和為1。
- Sensitivity：unweighted directed PageRank，以對照報告按目的地數分攤的公式。

## Clustering Coefficient

- **Report-specified**：`C_i=2E_i/[k_i(k_i-1)]`。
- **Implementation unspecified**：directed／undirected、weighted／unweighted、library與reciprocal edge處理。
- **Primary reconstruction**：移除loops，把directed graph投影成undirected simple graph；任一方向存在即視為一條undirected edge；計算unweighted local clustering。
- 理由：這是最接近報告所列公式的可執行解讀。限制是會忽略方向、reciprocity與flow magnitude。
- Synthetic triangle加tail驗證：triangle-only鄰接點係數1，連tail的節點為1/3。
- Sensitivity A：NetworkX directed unweighted clustering（Fagiolo-style directed triangles）。
- Sensitivity B：undirected weighted clustering，以最大weight正規化後的幾何平均定義。

## Library behavior verification

本機鎖定NetworkX 3.4.2。Synthetic graph含5 nodes、asymmetric directions、unequal weights、1個self-loop與1個sink；實際輸出及core construction checks見validation JSON。NetworkX官方文件確認[weighted betweenness把weight解讀為distance](https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.centrality.betweenness_centrality.html)、[directed eigenvector使用left／predecessor語意](https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.centrality.eigenvector_centrality.html)、[PageRank可指定alpha、weight與dangling](https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.link_analysis.pagerank_alg.pagerank.html)，以及[directed／weighted clustering另有專門定義](https://networkx.org/documentation/stable/reference/algorithms/clustering.html)。官方目前stable頁面版本可能高於本機版，因此契約以本機3.4.2 synthetic execution結果為直接驗證基準。

## Phase 5 sensitivity plan

Phase 4.2只設計、不在core graph執行：

- Betweenness：primary unweighted directed；比較inverse-flow與inverse-log-flow。
- Eigenvector：primary unweighted left；比較weighted left與unweighted right。
- PageRank：primary weighted；比較unweighted。
- Clustering：primary undirected unweighted；比較directed unweighted與undirected weighted。
- Self-loop：對primary排除loop的metrics保留retain-loop sensitivity；weighted degree另比較exclude-loop版本。

任何Phase 5未收斂、NA或不可達情況必須明確回報，不能靜默補0。
