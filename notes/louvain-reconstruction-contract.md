# Phase 6.0｜Community Detection / Louvain Reconstruction Contract

## Evidence boundary

- **Report-specified**：核心期間為2023/01–2024/12；研究稱網絡為directed weighted並使用Louvain；正文Q約0.665、contribution sum為0.66574，約11個生活圈。
- **Report-implied**：報告以modularity說明生活圈，但不足以識別實際graph projection或函式庫。
- **Implementation unspecified**：是否轉無向、reciprocal merge、self-loop、modularity實作、resolution、seed、node／edge order、library與version都未留下。
- **Reconstruction decision**：下列primary contract是可重現基線，不宣稱是原研究實作，也不以Q或群數對舊結果進行反向調參。

## Selected library and input behavior

固定使用NetworkX 3.4.2內建`networkx.algorithms.community.louvain_communities`。本機API與原始碼檢查確認它同時支援Graph及DiGraph，會依`seed`控制random shuffle；因此無向projection不是library limitation，而是本次研究語意決策。[NetworkX Louvain文件](https://networkx.org/documentation/networkx-3.5/reference/algorithms/generated/networkx.algorithms.community.louvain.louvain_communities.html)亦提供directed modularity gain並提醒node order會經random shuffle。

Primary仍採undirected weighted simple graph，因目標是把兩站雙向往來表示為total observed interaction strength，並使用weighted undirected Newman–Girvan modularity。Direction-preserving Louvain不是primary，也不在Phase 6.0執行。

## Final primary contract

| Item | Contract |
| --- | --- |
| Source | Phase 4.1 core 2023–2024 OD；2,782 nodes、1,125,519 directed edges |
| Projection | undirected simple weighted sum projection |
| Reciprocal pair | `w({i,j}) = w(i→j) + w(j→i)` |
| One-way pair | 保留唯一方向的完整`trip_count` |
| Self-loop | Louvain projection前移除；data-layer不修改 |
| Target weight | summed `trip_count` |
| Modularity | weighted undirected Newman–Girvan |
| Resolution | 1.0，library-standard reconstruction baseline |
| Louvain | NetworkX 3.4.2 `louvain_communities`，threshold=1e-7，max_level=None |
| Random seed | 42 |
| Order | station ID升冪；edge以端點排序後建立 |
| Isolates | 保留於target graph，指定singleton community |
| Relabel | 各community最小station ID升冪，重新編為1-based integer |

## Modularity contract

Primary使用：

\[
Q=\frac{1}{2m}\sum_{ij}\left[A_{ij}-\gamma\frac{k_i k_j}{2m}\right]\delta(c_i,c_j)
\]

其中`A`是sum projection後的undirected edge weight、`k_i`為weighted degree、`2m=Σ_i k_i`、`γ=1.0`。NetworkX實際以等價的community-sum式計算；[3.4 modularity文件](https://networkx.org/documentation/networkx-3.4/reference/algorithms/generated/networkx.algorithms.community.quality.modularity.html)明列公式、weight與resolution語意。Synthetic test另以獨立公式重算，與library結果在`1e-12`內一致。

## Self-loop decision

Data-layer仍保留1,504條self-loop edges／6,023,568 trips。Primary Louvain-layer移除，因生活圈契約描述站點間連結；同站借還不是跨站關係。NetworkX文件另警告大型self-loop會被視為近似「已縮約community」，可能使節點難以移入其他community，這與本資料的raw same-station trip語意不相符。

Retain-self-loop只保留為Phase 6.1 sensitivity；不可與primary混合。

## Projection QA on the full core input

Phase 6.0只建立projection並做守恆檢查，**沒有**在完整core graph執行Louvain或modularity optimization。

| QA item | Result |
| --- | ---: |
| Directed edges | 1,125,519 |
| Reciprocal unordered pairs | 375,424 |
| One-way unordered pairs | 373,167 |
| Projected undirected edges | 748,591 |
| Projected non-loop weight | 85,115,195 |
| Removed self-loop weight | 6,023,568 |
| Reconciled total | 91,138,763 |
| Isolates after loop removal | 0 |

`375,424 + 373,167 = 748,591`，且`85,115,195 + 6,023,568 = 91,138,763`。Reciprocal合併沒有讓flow weight消失，也沒有產生duplicate projected edge。

雖然本次core projection實際isolates為0，契約仍規定若未來符合相同schema的輸入出現loop-only node，該node保留並指定singleton community；synthetic validation已驗證NetworkX行為。

## Determinism and community labels

- Primary固定seed=42、NetworkX 3.4.2、內建backend、resolution=1、threshold=1e-7與node／edge ordering。
- 相同synthetic input與20-node bounded real subgraph各執行兩次，deterministic relabel後partition完全一致。
- Louvain原始community list順序與numeric IDs沒有語意。正式輸出只能在partition形成後，依每群最小station ID排序再給1-based label；不得把「第1群」當作跨run固定的生活圈名稱。

## Sensitivity and stability plan for Phase 6.1

下列只鎖定設計，本階段未在core graph執行：

- Projection：max、unweighted。
- Self-loop：retain。
- Resolution：0.5、1.5；primary仍為1.0。
- Seeds：primary 42；additional 7、19、73。
- 每次記錄community count與modularity；partition stability至少比較Adjusted Rand Index與Normalized Mutual Information。

不得掃resolution直到得到11群，也不得以Q接近0.66574作acceptance gate。Phase 6.1只在contract固定後執行，再把結果分類為exact/near、broadly similar、materially different或cannot verify，並保留implementation差異解釋。

## Validation

- 7-node synthetic graph包含reciprocal pair、one-way edge、兩組強群內邊、弱bridge、self-loop及移除loop後isolate。
- Sum／max／unweighted projection、self-loop removal、isolate singleton、獨立modularity與fixed-seed determinism全部通過；指定partition Q=0.4873417721518988，只是synthetic evidence。
- Bounded real validation只使用20 nodes／190 edges，目的限於parser、projection與fixed-seed函式行為；partition只保存hash，不回報或解讀community結果。
- Machine-readable evidence見[`louvain-contract-validation.json`](louvain-contract-validation.json)。

**狀態：Phase 6.0 contract finalized；完整core Louvain尚未執行。**
