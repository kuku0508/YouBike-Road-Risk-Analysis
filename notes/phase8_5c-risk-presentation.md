# Phase 8.5C — Risk Presentation Contract and Presentation-Ready Outputs

本階段將 Phase 8.5A canonical segment risk inputs轉為正式呈現用 long-form GeoParquet與靜態圖。它沒有建立排名、Top-N、binary hotspot、新 exposure cutoff、corridor、平滑或距離標準化風險。

## Locked inputs

- Phase 8.5A rows／fingerprint／SHA：106,049／`f9a3f6ba149cf8bdd4742d5e5857e03aa0a4bb8a1ab90f603199e10f103c4f14`／`dec4bf536fe692e69311371e02c905e02e19bdc49e30f45f88316e8dffcc750f`
- Phase 8.5A receipt fingerprint：`549e5344dab77b3fbb25df534ff45466734bfad49428c4c543cfaa7ed8c0fd70`
- Phase 8.5B QA／receipt fingerprints：`32eb8155f2f5ae8338747c18ec80b0b44082da3fe1e3116a7e10f4bb6c7afd8b`／`2ebd0e7e95fc435eb58284c6614b84ac7bec00863ac9f19512821b1d4886becb`
- Phase 8.5B結論維持 `supported`、`additional_stability_policy_required=false`；這是描述性支持，不是中位數門檻的統計最適性證明。

## Presentation universe

正式呈現只採既有 flags：平日 `weekday_high_flow=true` 53,032列、假日 `holiday_high_flow=true` 53,025列，合計 long-form 106,057列。沒有因 accident count、EPDO、CBI或length另加門檻，也沒有刪除CBI=0。

| Overlap state | Physical segments |
|---|---:|
| Weekday only | 1,665 |
| Holiday only | 1,658 |
| Both | 51,367 |
| Neither | 51,359 |
| Total | 106,049 |

Artifact grain是 `(day_type, physical_segment_id)`。幾何由方向中立BRouter canonical endpoints建立 EPSG:4326 WKB LineString；`segment_length_m`仍依EPSG:3826 deterministic重算。它不是Road.shp polygon或官方道路路段。

## CBI presentation contract

CBI、SRI、SSI逐值複製 Phase 8.5A，沒有day-type renormalization、clipping或改值。同一physical segment若同時進入兩種universe，其CBI完全相同。

所有106,049段中CBI>0的19,874段共同決定display thresholds：Q50 `0.05263157894736842`、Q75 `0.10526315789473684`、Q90 `0.21052631578947367`、Q95 `0.2631578947368421`。Ties不jitter；數值區間可能形成空class。`cbi_display_class`只是共同視覺metadata，不是risk category。

| CBI display class | Weekday | Holiday |
|---|---:|---:|
| zero | 36,757 | 36,905 |
| positive_le_q50 | 8,886 | 8,800 |
| q50_q75 | 3,559 | 3,526 |
| q75_q90 | 2,560 | 2,539 |
| q90_q95 | 511 | 503 |
| above_q95 | 759 | 752 |

`zero`只表示在研究期間、目前matched且classified fatal/injury accident population下沒有配對事故；不能寫成道路安全、完全沒有事故或事故為零。A3/PDO-only事故不可用，事故配對亦有明確排除。

## Exposure-adjusted rate presentation contract

平日使用 `weekday_epdo_per_1000_trips`，假日使用 `holiday_epdo_per_1000_trips`；numerator與denominator必須是相同day type。所有high-flow rows的day-type exposure均大於0，沒有把null rate轉成0。

Pooled positive long-form universe共有19,962個day-type observations，共同thresholds為Q50 `5.995695413920824`、Q75 `14.301804754822815`、Q90 `28.541459672710396`、Q95 `43.41743779132274`、Q99 `84.73853021973387`。

| Rate display class | Weekday | Holiday |
|---|---:|---:|
| zero | 39,207 | 46,888 |
| positive_le_q50 | 7,754 | 2,227 |
| q50_q75 | 3,309 | 1,681 |
| q75_q90 | 1,847 | 1,147 |
| q90_q95 | 431 | 567 |
| q95_q99 | 388 | 411 |
| above_q99 | 96 | 104 |

Display classes不clip、不winsorize canonical rate；tooltip或表格應顯示原始值。EPDO per 1,000代表每1,000次BRouter重建估計traversals的嚴重度加權事故負擔，不是CBI、絕對危險分數、GPS或官方交通量，也不能作因果解讀。

## Static figures and captions

- `phase8_5c_weekday_cbi.png`／`phase8_5c_holiday_cbi.png`：只顯示相應day-type exposure大於等於完整segment universe中位數的微路段；顏色是共同2023–2024 canonical CBI視覺class，CBI未依平假日重算。CBI只涵蓋目前可觀察且成功分類／配對的fatal/injury事故，PDO-only不可用。
- `phase8_5c_weekday_epdo_per_1000.png`／`phase8_5c_holiday_epdo_per_1000.png`：同day-type numerator／denominator；BRouter exposure是重建估計traversals，不是GPS或官方交通量。Median high-flow是正式presentation universe，不是統計最適門檻。
- `phase8_5c_high_flow_segment_count.png`：比較兩個long-form universe筆數，不是風險高低比較。
- `phase8_5c_rate_distribution.png`：以log1p軸呈現兩個high-flow rate distributions；只改視覺軸，raw rate未改。
- `phase8_5c_cbi_sparsity.png`：使用完整106,049段呈現CBI=0的86,175段（81.2596%）與CBI>0的19,874段（18.7404%）。

所有地圖使用相同extent、figure size、class ordering及各metric共同legend。色盤為neutral zero加色盲較易辨識的ordered sequential shades，未使用rainbow／jet。Line width不另行編碼flow、risk或length。

## Outputs、限制與readiness

- Canonical GeoParquet：`data/processed/risk/segment_risk_presentation_2023_2024.parquet`（大型artifact，不進Git）
- Machine-readable receipt：[`phase8_5c-risk-presentation.json`](phase8_5c-risk-presentation.json)
- Reproducible builder：`src/build_risk_presentation.py`
- Figures：`figures/phase8_5c_*.png`

限制仍包括PDO unavailable、BRouter estimated exposure、unsmoothed microsegment geometry、事故matching exclusions、10 m matching threshold為分析決策，以及不能作因果解讀。

Readiness：**PHASE 8.6 READY FOR SEPARATELY AUTHORIZED NEXT STAGE**。本階段沒有開始Phase 8.6。
