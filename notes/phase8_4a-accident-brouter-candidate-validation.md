# Phase 8.4A — 事故至 BRouter 流量路段候選驗證

## 結論

Phase 8.4A 已完成有界、唯讀的 spatial candidate validation。149,234 個 Phase 8.2 有向 micro-segments 依整數 microdegree 端點無方向化後，形成 106,049 個 direction-neutral physical segments；其中 62,864 個只有單方向 member，43,185 個同時具有正反方向 member，沒有 unexpected multiplicity。

本階段沒有正式將事故指派到 segment、沒有選 distance threshold、沒有以流量解 tie，也沒有計算 EPDO、CBI、風險分數或 hotspot。

## 鎖定輸入與粒度

- Phase 8.2 directed segment Parquet：149,234 rows；SHA-256 `68d0dec6498b7734b6cd09c7f94ec20cfa8708de31cbdb898b4ad65a0288f8ad`；內容指紋 `0925c99aa8f0022c953e09046bd7728d6a546cae6f28c81f68ccb5e35d6b2a04`。
- Phase 8.3C canonical accident road context：46,586 accidents；SHA-256 `d64954bf04877776968f7eb8e8bf6755d96c2ea75019d292325234c2df75cfa3`；內容指紋 `186f751e3a33ff2db01e7e44abe3255fff1008de3e9aaeb35056dd541e6b9f5b`。
- 輸出粒度固定為 one row per reconstructed accident；46,586 個 ID 唯一且守恆。1 件 `coordinate_unavailable` 不執行任何空間搜尋。

## Direction-neutral spatial view

事故資料沒有可靠行進方向，因此候選搜尋只使用方向中立的 physical microsegment view。每個 key 為兩個端點整數 tuple 經 lexicographic ordering 後的四欄 composite identity；A→B 與 B→A 只成為一個空間候選。Phase 8.2 的有向流量表完全不變，方向 member metadata 仍保留。

BRouter 端點由 EPSG:4326 microdegrees 除以 1e6 後轉成 EPSG:3826 LineString。距離是事故 Point 至 LineString 的最小平面距離（公尺），不是 midpoint 或 endpoint distance。空間搜尋不讀取 trip-weight 欄位。

## Global distance evidence

46,585 件可空間評估事故的 global nearest distance：

| 統計 | 公尺 |
|---|---:|
| min | 0.000000012 |
| mean | 31.9170 |
| P50 | 2.4057 |
| P75 | 5.1627 |
| P90 | 13.8594 |
| P95 | 35.5169 |
| P97.5 | 82.2080 |
| P99 | 857.6740 |
| max | 7,225.4673 |

描述性累積數量：≤0.5 m 6,214；≤1 m 11,479；≤2 m 20,389；≤3 m 26,926；≤5 m 34,511；≤10 m 40,434；≤20 m 42,931；≤30 m 43,878；≤50 m 44,879。這些 bins 不是正式 threshold。

## Road-context constrained diagnostics

候選資格使用 `direction-neutral LineString.intersects(Road polygon)`，因此包含完全位於、部分位於、穿越與接觸 polygon boundary 的 segments；不要求 midpoint 或 endpoints 位於 polygon 內。

37,859 件 `contained_valid_road` 中：

- global nearest 與 constrained nearest 相同：35,290（93.2143%，以全部 37,859 為 denominator）。
- 不同：1,328（3.5078%）。
- constrained candidate set 為空：1,241（3.2779%）。
- 有 constrained candidate 的 36,618 件，其 constrained distance P50/P90/P95/P99 為 2.1362/7.1955/10.6089/32.2877 m。
- constrained minus global distance 的 P50/P90/P95 為 0/0/0 m，P97.5 1.8763 m，P99 13.3182 m；差異只作政策證據，不表示任一候選「錯誤」。

候選集合大小分布：0=1,241；1=648；2=2,326；3–5=9,003；6–10=10,089；11–20=9,304；>20=5,248。

25 件 `contained_blank_road_id` 全部以 Phase 8.3B 保存的 stable feature index 重建唯一 polygon geometry；不建立 synthetic ROAD_ID。25 件皆有 context candidates，且 global/context nearest 全部相同。

8,701 件 `outside_reference_coverage` 只做 global search。其 distance P50/P90/P95/P97.5/P99 為 5.2232/57.6803/167.2309/1,258.5291/2,399.3490 m，mean 98.2531 m；明顯比 valid-road global distance（P50 2.2244 m、P90 7.9756 m、mean 16.6908 m）呈現更長尾。這是 reference coverage 與 BRouter network coverage 的描述性差異，不是刪除或配對規則。

## Ties、近似 ties 與 junction effect

- 988 件事故有多個 physical segments 共享 exact minimum distance。
- second-nearest minus nearest gap：≤0.1 m 6,248；(0.1,0.5] m 6,065；(0.5,1] m 4,983；(1,2] m 6,739；(2,5] m 10,035；>5 m 12,515；另1件缺座標。
- 這些數據能顯示 node/junction 附近候選可能密集，但不能單憑此判定事故發生於路口，也不能把任何 gap bin 升格成 ambiguity threshold。

## 正確性與決定性

- 使用 STRtree；沒有執行 46,585×106,049 的 full Cartesian 搜尋。
- 200 件 deterministic accident sample 以全部 106,049 physical segments 暴力計算；nearest key 與 distance 皆 200/200 完全一致。
- equal-distance presentation 依 canonical physical key 排序，但不代表選出 winner。
- 方向中立 artifact 指紋：`94b6de3529ac2b989d288ba4a67f58e8b7f23face25275881b01d2983e853496`。
- bounded validation 內容指紋：`53f1e8e741cb1269299db885a8d5b5794f5a444b39b260f878434ce57c7758e6`。
- 大型 Parquet 位於 `data/interim/` 且 Git ignored；小型 receipt 與 QA sample 可提交。

## 分析者仍須決定

本階段提供的 evidence 足以讓下一階段由分析者明確決定，但尚未替分析者決定：

1. 是否及如何設定正式 distance threshold。
2. exact tie 與 near-tie 的 ambiguity policy。
3. 是否採 global、Road-context constrained，或分狀態的 matching policy；尤其 1,241 個 context-empty cases。
4. 事故缺乏方向資訊時，方向中立 exposure 是否合併 A→B 與 B→A flow，以及其正式分母定義。
5. `outside_reference_coverage` 的 formal treatment。

狀態：**PHASE 8.4B READY FOR ANALYST MATCHING POLICY DECISION ONLY**。
