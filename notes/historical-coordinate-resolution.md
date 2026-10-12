# Phase 8.0A｜Historical station coordinate resolution

## Status

**HISTORICAL COORDINATES: PARTIALLY RESOLVED — ROAD ROUTING STILL BLOCKED**

本階段只建立歷史座標 evidence ledger、時間覆蓋判定與固定 artifacts；`full_routing_executed=false`，沒有執行 BRouter 全量路由、道路流量彙整或事故配對。

## Resolution contract

- Station identity 只接受 exact canonical station ID；站名、鄰近位置與模糊比對不得建立 identity。
- Tier 1 是 2023–2024 官方 dated evidence 直接覆蓋站點實際出現期間；Tier 2 是研究期間前後相同 official coordinate 將實際出現期間完整夾住。兩者才可進 routing-ready。
- Tier 3 單側支持、current-only、變更日期不明的 conflict 均 fail closed。
- 距離 bucket 只做 QA，不會自動裁決 precision 或 relocation。
- Evidence 只需覆蓋 station 實際出現在 core monthly OD 的期間；first／last observation 以月份邊界保守表示。

## Result

Phase 8.0 的 2,782／1,384／31／1,367 基準均重現。取得 4,193 筆 evidence rows；只有 5 個臺北站能以 2024-05-31 與 2026-09-13 相同座標完整夾住其 2024/06 以後的 observed interval，故列為 Tier 2。這 5 站彼此沒有 non-self OD，routing-ready coverage 為 5/2,782 nodes（0.1797%）、0/1,124,015 non-self edges、0/85,115,195 trips。

其餘 2,777 站保留 unresolved：1,375 個在 2024-05-31 前已出現而單一 in-period snapshot 無法覆蓋早期期間；4 個只有單一 2024 snapshot；1,367 個只有 2026 current coordinate；31 個 2024／2026 座標衝突。沒有證據足以確認任何 2023–2024 relocation，也沒有證據足以證明完全沒有 relocation。

因此目前不建立 coordinate eras，也不將 routing contract 升為 v2。`unique directed OD pair` 語意暫時維持 v1，但不可據此開始 full routing；若後續取得 within-period relocation evidence，必須改為 `directed OD × coordinate-era combination`。

Machine-readable policy：[`historical_coordinate_resolution_policy.yaml`](../config/historical_coordinate_resolution_policy.yaml)。執行摘要：[`historical-coordinate-resolution-receipt.json`](historical-coordinate-resolution-receipt.json)。

## Immutable artifacts

- Evidence ledger：`data/interim/routing/station_coordinate_evidence.parquet`，4,193 rows。
- Accepted coordinate artifact：`data/processed/routing/routing_station_coordinates_2023_2024.parquet`，5 rows。
- Unresolved priority artifact：`data/processed/routing/routing_coordinate_unresolved.parquet`，2,777 rows。
- Conflict artifact：`data/interim/routing/routing_coordinate_conflicts.parquet`，31 rows。

大型 Parquet 依 `.gitignore` 留在本機，不 commit；SHA-256、row count、station-ID fingerprint 與 coordinate fingerprint 已寫入 receipt。後續 routing 不得重新抓 current API 取代這些固定 identities。

## Interpretation boundary

「沒有找到可公開下載的官方歷史檔」不等於「官方沒有保存歷史資料」。已發現 TDX 支援日期參數的歷史公共自行車站點查詢，但需要個人 API 憑證；本次沒有憑證，故沒有把文件範例當成已取得的資料。

## Phase 8.0B legacy evidence follow-up

`active_station_all.csv`新增54,459筆exact-ID mapped valid-coordinate evidence rows，但provenance無法追溯，且31 conflicts中20站的2023–2024 legacy rows已使用2026 coordinate，顯示座標可能來自事後static lookup。這些rows標記為`supporting_not_routing_accepted`；final accepted artifact仍為5 nodes，routing coverage仍為0 edges／0 trips。

## Phase 8.0C analyst override（後續重建決策）

Phase 8.0B 的 **NOT SUFFICIENTLY TRACEABLE** 證據結論完整保留。Phase 8.0C 沒有新增來源證據或把legacy CSV提升為Tier 1；它新增的是可逆的`routing-coordinate-assumption-v1`：只為本次重建，將exact-mapped legacy monthly coordinate作operational routing coordinate。

2,769個identity-mapped IDs中，2,756個至少有一筆有效且跨觀察月份完全相同的coordinate；13個雖identity resolved，但所有legacy coordinate皆缺失。另有13個core IDs沒有accepted exact identity mapping。因此final artifact為2,756 nodes；28個有座標的conflict仍標記`coordinate_conflict=true`，另3個無legacy座標的conflict保留在gap artifact。31/31均未從evidence ledger消失。

這項後續決策不修改本文件前述Phase 8.0A／8.0B當時的歷史狀態。最終執行結果與替換機制見[`routing-coordinate-finalization.md`](routing-coordinate-finalization.md)。
