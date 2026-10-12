# Phase 4.2 — Network Construction Contract

## Core graph definition

Primary reconstruction scope固定為2023/01–2024/12，source of truth是Phase 4.1的`data/processed/od/aggregate/core_2023_2024/od.parquet`。

\[
G=(V,E),\quad V=\{\text{unique station IDs}\},\quad
E=\{(i,j): \text{eligible OD }i\to j\},\quad
w_{ij}=\text{trip_count}_{ij}.
\]

- Graph class：NetworkX 3.4.2 `DiGraph`。
- Directed：是，origin→destination。
- Weighted：是；`trip_count`是flow strength／interaction intensity。
- Node identity：canonical station ID；station name只作display metadata。
- Parallel edges：不允許；Phase 4.1已聚合成每個OD pair一列。
- Self-loops：data-layer保留。

`trip_count`不是distance、cost或impedance，不得直接傳給shortest-path metric的`weight`參數。

## Core integrity validation

| Check | Phase 4.1 expected | Constructed graph | Status |
|---|---:|---:|---|
| Nodes | 2,782 | 2,782 | pass |
| Directed OD edges | 1,125,519 | 1,125,519 | pass |
| Sum of `trip_count` | 91,138,763 | 91,138,763 | pass |
| Self-loop edges | 1,504 | 1,504 | pass |
| Self-loop trips | 6,023,568 | 6,023,568 | pass |
| Duplicate OD keys | 0 | 0 | pass |
| Null station IDs | 0 | 0 | pass |

這只是construction-level integrity check。沒有在core graph計算weighted degree、betweenness、eigenvector、PageRank、clustering或排名，也沒有輸出graph binary。

## Data layer與metric layer

Data-layer graph永遠保留self-loop，因同站借還是observed OD。Metric-layer依指標契約建立明確view，不使用全域blanket rule：

| Metric | Self-loop handling | Reason |
|---|---|---|
| Weighted Degree | 納入；in與out各計一次，total計兩次 | 與報告的in＋out公式一致，並透明反映library行為 |
| Betweenness | 明確排除 | 正長度最短路徑不需要loop；排除避免實作差異且不改節點可達性 |
| Eigenvector | Primary明確排除 | 報告未指定loop，保留會直接改變spectral score |
| PageRank | 納入 | 同站還車作為observed self-transition，會進transition probability |
| Clustering | 投影前排除 | Primary採undirected simple neighborhood公式，self-loop不屬於鄰居間triangle |

## Observation boundary

Core graph仍受臺北市來源機制限制：origin完整觀測範圍是臺北市，destination可含新北市。新北origin缺乏完整觀測，因此後續directional metric須解釋為「此資料來源所觀測的網絡」，不能外推成完整雙北行為網絡。

## Validation artifact

Machine-readable結果見[`network-construction-validation.json`](network-construction-validation.json)。驗證程式只在synthetic graph執行metrics，core只做counts、weights、loops與keys的integrity checks。

