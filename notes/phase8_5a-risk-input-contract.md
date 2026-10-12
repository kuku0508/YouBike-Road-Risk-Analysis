# Phase 8.5A — Accident Severity Reconstruction and Segment-Level Risk Inputs

## 結論

Phase 8.5A 已建立106,049列、每列一個direction-neutral BRouter physical microsegment的未平滑風險輸入。46,586件canonical accidents中149件歸為fatal、46,424件歸為injury、13件severity unavailable；39,705件同時具備Phase 8.4B正式match與可分類severity，進入segment aggregation。

本階段沒有排序、Top-N、hotspot、空間平滑、任意低流量排除或Phase 8.5B分析。

## Severity與EPDO契約

- **FACT：**使用Phase 8.3A-2已驗證的accident-level death、2–30日死亡與injury counts；不重新加總party rows。
- **ANALYTICAL DECISION：**`death_count > 0`或`death_2_30_day_count > 0`歸為fatal；fatal優先於injury。2–30日死亡納入fatal是本研究severity reconstruction決定，不宣稱是官方A1定義。
- Fatal contribution=193；injury contribution=117；係數直接採原研究，不重新fit或round。
- **DATA COVERAGE LIMITATION：**A3/PDO-only事故不可用。`pdo_accidents_available=false`，PDO component是`unobserved`，不是observed zero。本文的EPDO、SRI、SSI與CBI只能解讀為目前fatal/injury事故涵蓋範圍內的指標。

Severity守恆：149 fatal + 46,424 injury + 13 unavailable + 0 inconsistent = 46,586。

## Matching與day type交集

- Phase 8.4B matched：39,711。
- Matched and classified：39,705，其中124 fatal、39,581 injury。
- 未進segment aggregation：6,881，包括未正式match或severity unavailable者；仍保留於上游accident QA，不被刪除。
- Day type沿用Phase 7.3 authoritative `2020_2025假日.fst`之`IsHoliday`：weekday 30,088；holiday 9,617；unresolved 0。沒有以星期幾heuristic替代。

## Segment universe與CBI

完整universe固定為106,049個physical microsegments，包括86,175個零matched事故segments；19,874個segments至少有一件事故。單一microsegment最大38件事故、最大EPDO 4,446。

共同normalization：

- `SRI_i = accident_count_i / max(accident_count)`
- `SSI_i = EPDO_i / max(EPDO)`
- `CBI_i = SRI_i + SSI_i`

Weekday／holiday不各自重新normalization。max SRI=1、max SSI=1、CBI範圍0–2。CBI分布P50=0、P75=0、P90=0.05263、P95=0.10526、P99=0.26316、max=2。

## EPDO守恆

- Total EPDO：4,654,909
- Weekday EPDO：3,527,364
- Holiday EPDO：1,127,545
- Weekday + holiday = total：通過

事故數、fatal/injury與EPDO均exact integer conservation；每個eligible accident只屬於一個physical segment。

## Exposure、median flags與rates

Exposure沿用Phase 8.4B direction-neutral artifact，代表BRouter重建的estimated traversal exposure，不是GPS實測、自行車人次或官方交通量。

- Total exposure median：6,618
- Weekday median：4,352；`>= median` high-flow segments 53,032
- Holiday median：1,983；`>= median` high-flow segments 53,025
- Zero denominator：total 0；weekday 2,404；holiday 1,724。零分母rate為null，不填0、不填infinity、不加epsilon。

EPDO per 1,000 estimated trips分布：

| Rate | Non-null | P50 | P90 | P95 | P99 | Max |
|---|---:|---:|---:|---:|---:|---:|
| Total | 106,049 | 0 | 4.7370 | 17.0522 | 175.9398 | 277,875 |
| Weekday | 103,645 | 0 | 4.3980 | 17.4303 | 195.9799 | 312,000 |
| Holiday | 104,325 | 0 | 0 | 6.0734 | 100.3673 | 175,500 |

極端raw microsegment rates與低exposure高度敏感；此觀察正是Phase 8.5B需要另外設計stability policy的理由。本階段不據此宣稱任何segment最危險，也不設定最低exposure cutoff。

## Artifact與界線

- Canonical artifact：`data/processed/risk/segment_risk_inputs_2023_2024.parquet`
- Fingerprint：`f9a3f6ba149cf8bdd4742d5e5857e03aa0a4bb8a1ab90f603199e10f103c4f14`
- Parquet SHA-256：`dec4bf536fe692e69311371e02c905e02e19bdc49e30f45f88316e8dffcc750f`
- Grain：one unsmoothed routing microsegment per row。

沒有合併相鄰segment、corridor smoothing、Road.shp aggregation、spatial smoothing或排名。

狀態：**PHASE 8.5B READY FOR SEPARATELY AUTHORIZED STABILITY AND PRESENTATION POLICY**。
