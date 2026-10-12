# Phase 5.0｜SNA sensitivity results

## Interpretation boundary

- **Report-specified**：原報告只提供部分公式，沒有足以辨識下列variants的實作資訊。
- **Reconstruction decision**：所有variants依`network-metric-contract-v1`執行，只用來量化排名對重建選擇的敏感程度。
- **Sensitivity result**：Spearman使用全2,782 nodes的average ranks；Top 20 overlap使用各欄依值降冪後的前20站。

| Primary vs sensitivity | Spearman rho | Top-20 overlap | Reading |
| --- | ---: | ---: | --- |
| unweighted betweenness vs `1/flow` distance | 0.731506 | 6/20 (30%) | 排名對flow-distance choice明顯敏感 |
| unweighted betweenness vs `1/log1p(flow)` | 0.939601 | 8/20 (40%) | 全體次序接近，但頂端名單仍有差異 |
| unweighted-left eigenvector vs weighted-left | 0.926136 | 0/20 (0%) | 全體相關高，Top 20完全不同 |
| unweighted-left eigenvector vs reverse/right | 0.860915 | 12/20 (60%) | direction semantics會改變部分高排名站 |
| weighted PageRank vs unweighted | 0.942395 | 3/20 (15%) | 全體相關高，Top 20對flow weighting高度敏感 |
| undirected clustering vs directed | 0.984156 | 12/20 (60%) | 全體最穩定，但頂端仍非完全一致 |
| undirected unweighted vs undirected weighted clustering | -0.543700 | 0/20 (0%) | 對weight definition方向性反轉，最敏感 |

## Execution evidence

- Exact betweenness runtimes：primary 226.88 s；inverse-flow 678.24 s；log-inverse-flow 582.06 s。
- 其他主要耗時：undirected primary clustering 138.73 s、directed clustering 574.79 s、weighted clustering 752.22 s。
- 全部metric計算累計約2,997.67 s；checkpoint續跑後最後彙整呼叫約9.22 s。Peak working set約1.60 GiB。
- 每欄皆通過finite、range／norm／sum等契約檢查；完整數值見[`sna-sensitivity-summary.json`](sna-sensitivity-summary.json)。

## Consequence

Primary結果可依既定contract重現，但weight、direction與projection選擇對Top 20可能有實質影響，尤其weighted clustering、weighted eigenvector與PageRank。因此後續只能把primary稱為本重建的主規格，不能倒推為原研究唯一實作。
