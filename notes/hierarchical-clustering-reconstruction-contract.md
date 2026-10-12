# Phase 7.2｜Hierarchical Clustering Reconstruction Contract

## Outcome

**HIERARCHICAL CLUSTERING INPUTS: READY FOR THE ANALYST-SELECTED 2023–2024 VARIANT**

原報告hierarchical文字仍是2022–2024；Phase 7.3由分析者明確選擇核心network period 2023–2024作為reconstruction variant。現在已具備平日／假日各一份2,782×72未標準化矩陣，但尚未執行StandardScaler、Ward、cut或dendrogram。

## Report evidence recovered

- **Report-specified**：p.7與p.27都寫2022–2024。
- **Report-specified**：平日與假日分開；每個小時各自建立SNA。
- **Report-specified**：每站以Betweenness、Eigenvector、PageRank彙整為72個變數。72可由3 metrics × 24 hours對應，但乘法關係是依正文與附錄結構作的reconstruction interpretation。
- **Report-specified**：Euclidean distance＋Ward.D2 linkage。
- **Report-specified output**：附錄Figure 45平日dendrogram顯示5群；Figure 49假日dendrogram顯示4群。
- **Implementation unspecified**：centrality的direction／weight／self-loop版本、scaling、missing-value處理、R版本、精確cut height／函式呼叫、站點universe與outlier policy。
- **Report-implied**：附錄dendrogram軸標`hclust(*, "ward.D2")`，支持R `stats::hclust`家族實作；R版本及完整code未知。

完整期間證據見[`hierarchical-period-evidence.md`](hierarchical-period-evidence.md)。

## Target input and grain

Hierarchical execution需要兩份獨立矩陣：

1. `data/processed/network/hourly_2023_2024/hierarchical_weekday_72_features.parquet`
2. `data/processed/network/hourly_2023_2024/hierarchical_holiday_72_features.parquet`

每份資料一列一個`station_id`，精確72個features：

- `betweenness_h00`…`betweenness_h23`
- `eigenvector_h00`…`eigenvector_h23`
- `pagerank_h00`…`pagerank_h23`

**Weighted Degree版本：不適用。** 原報告hierarchical feature list沒有Weighted Degree，也沒有Clustering Coefficient；不得沿用K-means四features。未來三項centrality的metric variants必須由2022–2024逐時network contract另行鎖定，不能直接把Phase 5全期間metrics複製72次。

Phase 7.3固定使用core primary OD union的2,782 nodes，使平日與假日矩陣完全對齊；72欄皆finite。任何NaN、Inf、重複ID、少欄或多欄均fail closed，不impute、不靜默drop。

## Preprocessing

報告沒有說明scaling。Primary reconstruction採：

```text
StandardScaler(with_mean=True, with_std=True)
```

每一個hour×metric feature在同一day type的站點間獨立標準化。這是**Reconstruction decision**：三種centrality的尺度不同，Euclidean／Ward對尺度敏感。Primary不做log、winsorization、trimming或outlier removal；極端network-role stations全部保留。No-scaling只列為sensitivity。

## Distance and linkage

| Setting | Contract | Evidence status |
| --- | --- | --- |
| Distance | Euclidean | Report-specified |
| Linkage | Ward.D2 | Report-specified |
| Report implementation | R `hclust` family indicated by plot label | Report-implied；version unspecified |
| Reconstruction implementation | SciPy 1.17.1 `scipy.cluster.hierarchy.linkage(method="ward", metric="euclidean")` | Reconstruction decision |

SciPy primary語意是對Euclidean observation vectors執行Ward variance minimization。它與未留下版本的R環境不宣稱byte-identical；未來正式執行必須保留SciPy版本、ordered input fingerprint與linkage matrix hash。

## Cut rule and labels

- Weekday：fixed `maxclust=5`，依Figure 45顯示的五群重建。
- Holiday：fixed `maxclust=4`，依Figure 49顯示的四群重建。
- 報告沒有交代精確cut height或完整切割code；不能宣稱原研究一定用`cutree(k=...)`。
- Raw hierarchy labels無語意。正式partition依每群最小station ID升冪重新編1-based ID；ID不代表高低或功能。
- 不得因想對上舊圖而改scaler、linkage或群數。

## Dendrogram contract

正式execution必須保存：

- 完整linkage matrix。
- station ID ascending輸入順序及SHA-256 fingerprint。
- deterministic full leaf order與station-ID sidecar。
- linkage matrix SHA-256。
- full hierarchy的dendrogram圖，但視覺圖不顯示2,000+個站名文字，以免不可讀。

圖可以隱藏leaf labels或採截斷顯示作閱讀輔助，但抽樣圖不得冒充full hierarchy；完整樹結構仍須保存在artifact。

Cophenetic correlation可作representation-fidelity secondary diagnostic，不是原報告selection criterion，也不得用來反向挑選最像報告的linkage。

## Relationship to K-means

原報告只說Ward概念與K-means相似，沒有說hierarchical用來驗證K=4。兩者目前不能直接做ARI／NMI：

- K-means：2023–2024、四個全期間features、單一k=4 partition。
- Hierarchical：2022–2024、平／假日各自72個逐時features、平日5群／假日4群。

只有未來期間、feature definition及station universe真正一致時，才可做membership ARI、NMI與cross-tab；否則只比較方法與feature-profile，禁止把不同母體的membership硬接在一起。

## Sensitivity plan

Primary保持StandardScaler＋Ward／Euclidean。有限sensitivity：

- Scaling：no scaling。
- Linkage：complete、average；distance仍為Euclidean。

不跑完整cross-product，不用sensitivity結果反向修改report-specified Ward.D2。不同linkage的cophenetic correlation只作secondary diagnostic。

## Validation

- 10-row×4-feature synthetic matrix包含刻意不同的原始尺度、三個清楚結構與一個extreme observation；station ordering、StandardScaler、Euclidean pairwise distances、Ward linkage shape、fixed cut、deterministic relabel及outlier retention全部通過。正式72-feature欄位契約另由exact feature-selection test鎖定。
- 12-row bounded real sample使用Phase 5的Betweenness／Eigenvector／PageRank，只驗證三metric plumbing、排序、scaling、Ward與determinism；它**不是72-feature target、不是2022–2024結果、不可解讀partition**。
- Full hierarchical execution flag為false；目標weekday／holiday input files不存在。
- Machine-readable證據見[`hierarchical-contract-validation.json`](hierarchical-contract-validation.json)。

## Readiness gate

Phase 7.3已完成分析者選定之2023–2024 variant的48個network buckets、三項逐時metrics與兩份72-feature matrices。下一步可依既有contract執行StandardScaler＋Ward.D2，但必須持續標示period limitation，且不得把這套輸出寫成report-complete 2022–2024 reproduction。

## Phase 7.4 execution status

分析者選定的2023–2024 variant已依本contract完成正式執行：weekday／holiday各自獨立StandardScale、Euclidean＋SciPy Ward、完整2,782-leaf dendrogram、report-reference k=5／k=4 cuts、complete／average／no-scaling sensitivities及deterministic重跑皆通過。執行結果見[`hierarchical-results.md`](hierarchical-results.md)與[`hierarchical-run-receipt.json`](hierarchical-run-receipt.json)。原報告2022–2024期間限制仍保留。
