# Phase 3.7 — 2023/01–2025/03 Full-Period Cleaning

## 狀態

**FULL-PERIOD CLEANING: COMPLETE**

27個月份的source gate、cleaning、quarantine、Parquet reread、record conservation、raw multiset、receipt與atomic finalize均通過。此階段沒有建立OD matrix、graph、SNA、clustering、routing或事故整合。

Machine-readable manifest：[`full-period-cleaning-manifest.json`](full-period-cleaning-manifest.json)。每月receipt位於`runs/full_cleaning/phase3.7-full-period/receipts/`。大型cleaned與quarantine outputs位於`data/processed/cleaned/year=YYYY/month=MM/`，保留在本機且不進Git。

## 範圍與守恆

| Period | Input | Accepted | Quarantine | Conservation |
|---|---:|---:|---:|---|
| Core：2023/01–2024/12 | 92,700,026 | 92,699,907 | 119 | passed |
| Extended report period：2023/01–2025/03 | 109,713,899 | 109,713,772 | 127 | passed |

Quarantine rate為0.00011576%。127筆皆為`serialization_unsafe_unapproved_destination_station_raw`，均保留safe raw envelope、exact Base64、source row與parser provenance；這是可審查的分流，不是刪除。出現quarantine的月份為2023/03–07、2024/07–12與2025/01。

## Schema與bike type

- 6-column canonical path：80,305,284 records，`bike_type=None`為structural absence，不當成缺失錯誤。
- 7-column path：28,444,744一般車、963,871電輔車。
- 沒有發現未審查的bike type；每月schema、header、record count與source SHA-256均通過既有Phase 2.5／3 evidence gate。

Bike-type counts以input為分母，其中quarantine為94 structural null、31一般車、2電輔車；不與accepted-only Parquet分母混用。

## Station repair execution

| Grain | Result |
|---|---:|
| Approved origin sides | 571,546 |
| Approved destination sides | 592,389 |
| Approved sides total | 1,163,935 |
| Trips with at least one approved repair | 1,118,165 |
| Origin only repaired | 525,776 |
| Destination only repaired | 546,619 |
| Both sides repaired | 45,770 |
| Neither side repaired | 108,595,607 |

Tier 1 subtype station sides：1A 637,743、1B 490,507、1C 35,685。Candidate-only 4,305 sides、ambiguous 947,098 sides、unresolved 279 sides與not-an-error 1,784,176 destination sides依契約保留；未進行fuzzy matching、prefix guessing、suffix removal或新mapping。

## Illegal UTF-8

- Illegal byte count：254,831。
- Affected station fields：210,267。
- Affected records：202,123；origin 102,224、destination 108,043、兩端同時 8,144。
- Approved exact-byte repair：210,139 affected sides／201,996 affected records進入accepted Parquet。
- Unapproved unsafe：127 destination sides／127 records進quarantine。

Raw identity由exact Base64保留與比對，未使用replacement character代替證據。

## Repeated records

- Repeated groups：397,971。
- Involved records：803,160。
- Excess copies：405,189。
- Multiplicity groups：2次 392,348；3次 4,459；4次 909；5次以上 255。

全部保留。每月raw multiset fingerprint在accepted與quarantine重組後與input相等，沒有deduplication、silent row loss或duplicate creation。

## Phase 3A cross-check

27月、109,713,899 total records、monthly counts、encoding bytes／fields／records、bike types、repeated groups／involved／excess、missing endpoints與duration validation均與Phase 3A evidence一致。時間與duration只做validation，沒有因duration=0、>24h、>7d或timestamp關係特殊而排除record。

## Fail-closed與續跑驗證

1. 2024/08首次執行因Phase 3 monthly sparse issue map省略zero-count key而fail closed。最小修正將省略key解釋為0，並新增regression test；前19個finalized months經identity與hash驗證後安全重用。
2. 27月完成後，初版global summary因把整數與Phase 3 `{count, percentage}`物件直接比較而fail closed。Monthly sums與`count`完全一致；最小修正、regression test與27個output hash重驗後，全部global cross-check為true。

兩次失敗都沒有留下partial finalized partition，也沒有改raw data、allowlist或repair policy。

## Performance與輸出

- Sum of monthly wall clock：12,663.59秒（約3小時31分4秒）。
- Monthly throughput：min 7,268.65／median 8,808.43／max 9,950.81 records/s。
- Approximate peak working set：672,587,776 bytes（約641.43 MiB）。
- Raw ZIP total：1,326,674,544 bytes。
- Cleaned Parquet total：1,471,049,497 bytes。
- Quarantine JSONL total：180,707 bytes。

## Validation

- Final test suite：83 tests passed。
- 27/27 monthly receipts：`validation_status=passed`。
- 27/27 source/output hash identities在final manifest rebuild時重驗成功。
- Manifest `status=complete`；Phase 3A cross-check欄位全部為`true`。
- Raw ZIP與`data/processed/cleaned/`均由`.gitignore`排除；receipts、manifest、程式、測試與本文件可提交。

## 後續邊界

下一個最小任務是由分析者定義OD inclusion policy，至少要決定quarantine、missing endpoints、candidate-only、ambiguous、unresolved、cross-city destination-only及station historical validity如何影響OD eligibility。本階段不解決這些方法問題，也不自行建立OD。
