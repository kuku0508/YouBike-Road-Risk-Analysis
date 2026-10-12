# Phase 3.1 Station-name anomaly forensic analysis

本階段只對 2023/01–2025/03 已完成的 Phase 3 聚合證據做站名字串鑑識與候選評估。沒有修改 raw／canonical records，沒有執行 repair、normalization、merge、delete、deduplication、station reconciliation 或 OD construction。Phase 3 JSON 的執行前後 SHA-256 相同。

## 結論摘要

- **Observed in raw data：**extended report period 的非法 UTF-8、原生 `�`、`?`、不平衡括號分別影響 202,123、145,367、408,727、1,294,748 筆 records。Phase 3 record-union count 是正式分母；candidate table 的 value-involvement count 可能因同一 record 兩端受影響而重疊。
- **Reconstruction interpretation：**8 個非法 byte patterns 都不能只靠殘存 bytes 可逆解碼（byte-recoverable = 0），但 8 個皆在站點 metadata 得到單一候選，因此屬「external-evidence text-recoverable」，不是純解碼修復。
- **Reconstruction interpretation：**7 個原生 `�` 與 10 個 `?` raw values 均得到單一 metadata 候選；原始替代字元本身仍不可逆。
- **Reconstruction interpretation：**31 個不平衡括號／疑似截短值中，18 個有單一候選、10 個有多候選、3 個無候選。此類 record-level 只有 368,077／1,294,748（28.4285%）落在 unique-supported；至少 926,106（71.5279%）仍 ambiguous。
- **Reconstruction interpretation：**1,528 個 destination-only 非空名稱中，1,311 個 exact-match 新北市官方目前站點（1,784,172 records）；217 個（21,940 records）未解。這支持將前者由「疑似站名問題」重新詮釋為 cross-city / station-universe issue，但不回寫 Phase 3。

## 範圍與方法

| 項目 | Core period | Extended report period |
| --- | ---: | ---: |
| 月份 | 2023/01–2024/12 | 2023/01–2025/03 |
| Phase 3 total records | 92,700,026 | 109,713,899 |
| 已分類的任一四類站名 anomaly record union | 1,877,700 | 2,046,061 |
| unique-supported | 1,008,253（53.6962%） | 1,119,397（54.7099%） |
| ambiguous | 868,919 | 926,106 |
| unresolved | 528 | 558 |

上述 union 由 `data/interim/phase3-profile.sqlite` 的月別 unique OD 聚合重算，避免兩端及 issue 間重複相加。少數 Phase 3 records 因另一端站名缺失而未進入 OD 聚合：core／extended 的原生 `�` 各 1 筆、`?` 各 2 筆、不平衡括號各 7 筆；它們仍保留在 Phase 3 正式 count，沒有被刪除。因所有 `�` 與 `?` unique values 都是 unique-supported，這些差額不改變 unique-value 結論；不平衡括號的 7 筆差額保守留為未分配。

## Compatibility matrix：repairability assessment

以下 `Records` 使用 extended Phase 3 的正式 record-union count。`Unique-supported / Ambiguous / Unresolved` 的 unique 欄是候選表中的 raw value 數；record 欄採 record union，不把 value-involvement 直接相加。

| Issue | Records | Unique values | Unique-supported | Ambiguous | Unresolved | 判讀 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Illegal UTF-8 | 202,123 | 8 | 8 values / 202,123 records | 0 | 0 | 0 byte-recoverable；8 僅能靠外部唯一證據支持文字候選 |
| Native `�` | 145,367 | 7 | 7 values / 至少 145,366 records | 0 | 0 | 原 byte 已不存在；1 record 不在 OD 聚合但不改變 value status |
| `?` | 408,727 | 10 | 10 values / 至少 408,725 records | 0 | 0 | `?` 位置作 wildcard 候選 gate，不把猜字當證明 |
| Unbalanced / truncated | 1,294,748 | 31 | 18 values / 368,077 records | 10 values / 926,106 records | 3 values / 558 records | 另 7 records 不在 OD 聚合，保守未分配 |
| Destination-only | 1,806,116 | 1,528 | — | — | 217 values / 21,940 records | 1,311 values / 1,784,172 records exact-match 新北官方目前站點，標 `not_an_error`；另有 4-record Phase 3 差額來自空白站名，不是可鑑識 station string |

## A. Illegal UTF-8 bytes

- **Observed in raw data：**8 個跨欄位去重的 raw byte patterns；起點出現 102,224 次、終點 108,043 次。欄位 occurrence 可同時落在同一 record，不能當 union。
- **Reconstruction interpretation：**每個 pattern 都包含被 `surrogateescape` 保留的非法尾端 bytes；把 Base64 解回 bytes 後可重現原始欄位 bytes，但嚴格 UTF-8 仍失敗。這是「bytes 無損保存」，不是「文字可逆恢復」。
- **Evidence：**8 個 pattern 的固定前綴／後綴候選在臺北或新北 metadata 中各只留下同一 `(station name, station ID, city)`。因此 candidate table 標 Level B `unique_supported`；未改動原字串。
- **Assumption：**上游為何截斷與遺失了哪些 bytes 仍未知；不能把候選說成由 encoding 本身解出。

## B. Native replacement character `�`

- **Observed in raw data：**7 個 unique station strings；起點 73,246、終點 78,388 occurrences。
- **Reconstruction interpretation：**7 個均有單一官方／歷史快照候選，標 Level B `unique_supported`。由於 `�` 已存在於 raw text，原始 bytes 不可由該字元反推。
- **Assumption：**它與 illegal UTF-8 的外觀可相鄰，但兩類證據來源不同，不能合併成同一 encoding issue。

## C. Question mark `?`

- **Observed in raw data：**10 個 unique strings；`?` 的位置不固定，可能在首字、中段或括號內。起點 209,947、終點 213,404 occurrences。
- **Reconstruction interpretation：**把 `?` 僅當未知 span 產生候選後，10 個均有單一 metadata `(name, ID, city)` 命中，故標 Level B `unique_supported`。
- **Assumption：**無法僅由 `?` 證明上游 replacement 機制；candidate value 不會回填到 records。

## D. Unbalanced parentheses / truncated names

- **Observed in raw data：**31 個 unique values，但影響 1,294,748 records，是四類中最大者。
- **Reconstruction interpretation：**prefix gate 只產生候選。18 個只有一組 metadata name/ID/city，10 個因短前綴同時命中基礎名稱與較長名稱而保留 ambiguous，3 個無候選而 unresolved。
- **風險：**若只補右括號或選最長 prefix，會在 926,106 records 上做沒有唯一證據的決定；目前不得這樣做。

## E. Destination-only station universe

| Recommended interpretation | Unique values | Records | Evidence |
| --- | ---: | ---: | --- |
| matched New Taipei station | 1,311 | 1,784,172 | 新北市政府 2026/09/14 即時站點 snapshot exact name + unique ID |
| matched Taipei station | 0 | 0 | 兩個臺北 snapshots 無 exact-only match |
| matched historical-only station | 0 | 0 | 本次有限歷史快照無額外 exact-only match |
| ambiguous | 0 | 0 | exact-match 分類沒有多 ID／多城市衝突 |
| unresolved | 217 | 21,940 | 現有 snapshots 無 exact match |

**Recommended reclassification：**保留 Phase 3 原始 `destination_only_station` 統計不變；在下一階段語意層將 1,311 個 exact-match 新北值標成「合法跨市／station-universe issue」，不再稱為 dirty station name。這個建議只證明 identity feasibility；目前 snapshot 不提供 `valid_from`／`valid_to`，不能單獨證明每站在每個歷史月份的營運狀態。

## Evidence sources

1. 臺北市官方 YouBike 2.0 即時資訊 snapshot，2026/09/13，1,800 rows：`https://tcgbusfs.blob.core.windows.net/dotapp/youbike/v2/youbike_immediate.json`。
2. 新北市政府交通局 YouBike 2.0 Open Data API snapshot，2026/09/14，1,606 rows：`https://data.ntpc.gov.tw/api/datasets/010e5b15-3823-4b20-b401-b1cf000550c5/csv?page=0&size=5000`。
3. 第三方保存之臺北官方 feed snapshot，2024/05/31，1,415 rows：`https://github.com/LittleFish-Coder/youbike-info-collector/blob/master/result/2024-05-31.csv`。僅作歷史日期點輔助，不冒充官方 historical master。
4. Phase 3 immutable evidence：`notes/data-quality-profile.json` 與 `data/interim/phase3-profile.sqlite`。每個檔案的 SHA-256、snapshot date、authority 與 URL 見 `notes/station-name-forensics-evidence.json`。

## 未解問題與 Phase 3.2 policy input

- 需要分析者決定：Level B 的「單一 metadata 候選」是否足以進入 deterministic repair allowlist，或須再要求同月份／相鄰月份 Level A 證據。
- 10 個 ambiguous truncated values、3 個 unresolved truncated values與 217 個 destination-only unresolved values應維持 quarantine／原值保留，除非取得新證據。
- 目前沒有完整 2023–2025 historical station master 或有效期間，不能建立歷史站點 SCD。
- `_1`／`_2` 仍須逐字保留；本階段沒有對它們正規化。
- 若 Phase 3.2 採 repair，規則應是明示 raw-byte/Base64 allowlist → 唯一 station ID，並保存原值、證據版本、mapping 版本與不可修復 fallback；禁止 fuzzy auto-correction。

## Reproducibility and validation

- `src/station_name_forensics.py` 只以 SQLite read-only URI 讀 Phase 3 聚合，輸出 candidate CSV 與 evidence JSON。
- CSV 每列保存 raw display、Base64、月份、起終點 occurrences、候選 ID／城市、evidence level、來源與 status；status 只使用 `unique_supported`、`ambiguous`、`unresolved`、`not_an_error`。
- 測試涵蓋 Base64／surrogateescape round-trip、候選不改 raw、ambiguous 不升格、數字後綴保留、Phase 3 evidence hash 不變。
