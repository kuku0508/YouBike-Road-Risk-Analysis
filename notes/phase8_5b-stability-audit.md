# Phase 8.5B — Microsegment Risk Stability and Presentation Audit

本階段只檢查 Phase 8.5A 微路段風險率的分母穩定性與未來呈現可讀性；沒有建立危險路段排名、Top-N、hotspot、新 exposure cutoff、corridor、平滑或距離標準化指標。

## Locked input 與方法

- Canonical input：`data/processed/risk/segment_risk_inputs_2023_2024.parquet`
- Rows：106,049；content fingerprint：`f9a3f6ba149cf8bdd4742d5e5857e03aa0a4bb8a1ab90f603199e10f103c4f14`
- Parquet SHA-256：`dec4bf536fe692e69311371e02c905e02e19bdc49e30f45f88316e8dffcc750f`
- Phase 8.5A receipt fingerprint：`549e5344dab77b3fbb25df534ff45466734bfad49428c4c543cfaa7ed8c0fd70`
- High-flow flags完全沿用 Phase 8.5A 的完整 106,049 段 universe 中 `exposure >= median`；沒有重算或改門檻。
- `segment_length_m`由 canonical endpoints 的 microdegrees 還原 EPSG:4326，再投影至 EPSG:3826，計算相鄰端點直線長度。它是 BRouter routing microsegment geometry length，不是官方道路路段長度。

## Microsegment length QA

所有 106,049 段長度皆為有限正數；null、non-positive、non-finite 均為 0。

| min | P1 | P5 | P10 | P25 | P50 | P75 | P90 | P95 | P99 | max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.101 | 2.126 | 4.089 | 5.584 | 9.480 | 19.675 | 41.410 | 71.784 | 98.043 | 166.403 | 1,747.476 |

事故段長度中位數 26.573 m，無事故段 18.702 m。平日 high-flow／非 high-flow 長度中位數為 16.975／22.058 m；假日為 17.024／22.059 m。High-flow flag 的確與長度分布略有關聯，但沒有只保留某一極端長度類型。

## Full universe 與既有 median high-flow subset

單位均為 EPDO per 1,000 reconstructed estimated trips。Mean 對極端值高度敏感，只作背景診斷。

| Day type / universe | N | non-zero N | mean | P90 | P95 | P97.5 | P99 | P99.5 | max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Weekday full | 103,645 | 16,830 | 49.005 | 4.398 | 17.430 | 51.803 | 195.980 | 504.310 | 312,000.000 |
| Weekday high-flow | 53,032 | 13,825 | 2.585 | 7.129 | 14.745 | 23.516 | 41.443 | 54.052 | 433.333 |
| Holiday full | 104,325 | 7,461 | 23.027 | 0.000 | 6.073 | 24.845 | 100.367 | 280.074 | 175,500.000 |
| Holiday high-flow | 53,025 | 6,137 | 1.902 | 2.331 | 11.408 | 24.316 | 42.810 | 54.772 | 350.183 |

平日 high-flow 後 P95／P99／max 分別下降 15.41%／78.85%／99.861%。假日 P99／max 下降 57.35%／99.800%；P95 由 6.073 上升至 11.408（+87.83%），原因是 full universe 大量零事故段造成分布混合改變，不能把每個分位數都期待為單調下降。整體而言，最不穩定的 P99 與最大值大幅收斂，但極端值並未消失。

## High-flow P99 tail（aggregate，不是排名）

| Diagnostic | Weekday high-flow tail | Holiday high-flow tail |
|---|---:|---:|
| N | 531 | 533 |
| Tail threshold | 41.443 | 42.810 |
| Exposure min / P25 / P50 / P90 | 4,369 / 5,171 / 6,548 / 13,507 | 1,983 / 2,349 / 2,667 / 5,438 |
| Length min / P25 / P50 / P90 (m) | 3.435 / 16.748 / 46.773 / 135.198 | 2.115 / 13.530 / 33.461 / 111.356 |
| Accident count P50 / P75 / P90 / max | 4 / 6.5 / 10 / 38 | 3 / 5 / 8 / 38 |
| EPDO P50 / P75 / P90 / max | 468 / 760.5 / 1,170 / 4,446 | 351 / 585 / 936 / 4,446 |
| CBI P50 / P75 / P90 / max | 0.211 / 0.342 / 0.526 / 2 | 0.158 / 0.263 / 0.421 / 2 |

High-flow tail 的 exposure 下界正好受既有 median flag 控制，且其事故件數中位數為 4（平日）與 3（假日），不能概括為單一事故加極小分母。其長度中位數 46.773／33.461 m，均高於全體 19.675 m；因此沒有證據顯示極短微路段是 high-flow tail 的主要驅動因素。

## Exposure、length 與交互診斷

- 平日 exposure quartile 的 rate P99 由 Q1 的 1,258.065、Q2 的 308.309、Q3 的 50.330，降至 Q4 的 11.583；假日由 Q1 的 0（大量零事故）、Q2 的 309.524、Q3 的 50.852，降至 Q4 的 12.031。假日 Q1 的 max 仍為 175,500，說明 P99=0 是稀疏混合分布，不代表沒有極端值。
- Length quartile沒有呈現「最短 Q1 一致最極端」：平日 P99 為 120.619／179.753／167.382／330.696，假日為 53.863／98.938／72.671／173.948；兩者最高均在最長 Q4。
- 4×4 exposure × length matrix 顯示，低 exposure cell 的 P99 可很高且橫跨不同 length quartiles；高 exposure Q4 的各 length cells則明顯較穩定。這支持 denominator 是主要穩定性因素，沒有支持「低 exposure + 最短 segment」才是唯一來源。
- 上述 quartiles只作描述性 QA，不能升格為新 cutoff。

## CBI sparsity 與呈現限制

- CBI = 0：86,175（81.2596%）
- CBI > 0：19,874（18.7404%）
- 非零 CBI：P10/P25/P50 = 0.0526；P75 = 0.1053；P90 = 0.2105；P95 = 0.2632；P99 = 0.4737；max = 2.0。

全體 0–2 linear color scale 會把多數非零值擠在非常低的色階。未來視覺化可以另行評估 nonlinear color mapping、quantile legend 或 display clipping，但本階段沒有採用任何一項，也沒有改寫 canonical CBI。

## 結論與界線

`stability_conclusion = supported`：既有 median high-flow flags獲得描述性證據支持，可作後續正式 presentation universe；這不是 statistically proven optimal，也不是 hotspot policy。理由是 P99 與 max 大幅收斂、high-flow tail 不再是近零 exposure，且短微路段不是主要驅動因素。

`additional_stability_policy_required = false`：目前沒有證據要求先新增 arbitrary exposure cutoff 才能進下一階段；仍必須揭露尾端、零值稀疏、estimated exposure、PDO unavailable、微路段幾何與事故配對等限制。極端值仍存在，因此正式呈現不得將數值直接轉譯成因果或「最危險道路」。

Readiness：**PHASE 8.5C READY FOR SEPARATELY AUTHORIZED PRESENTATION / HOTSPOT POLICY DESIGN**。本階段沒有開始 Phase 8.5C。

Machine-readable完整矩陣、tails與指紋見 [`phase8_5b-stability-audit.json`](phase8_5b-stability-audit.json)。
