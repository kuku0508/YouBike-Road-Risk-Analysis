# Phase 3.4 Synthetic cleaning execution validation

本階段只用13筆完全合成records驗證station cleaning execution contract；沒有讀取任何真實月檔、沒有建立正式cleaned dataset，也沒有進行OD／SNA／clustering／routing。

## Batch contract

每筆parser canonical record先保留`borrow_time`、`return_time`、`duration_raw`、`bike_type`、`borrow_date`及四個parser provenance欄位，再對origin與destination各自執行相同契約。`_parse_warnings`以canonical JSON string保存，避免不同warning object keys造成Parquet struct schema drift，內容不刪減。輸出雙端的raw display、raw Base64、clean name、station ID、city、repair status、rule version、evidence tier與Tier 1 subtype。Raw Base64是exact bytes追溯依據；clean值永遠不覆寫raw evidence。

狀態行為如下：

| Status | Execution behavior |
| --- | --- |
| `approved_repair` | exact Base64命中後套用canonical name／ID／city，保留Tier 1 provenance |
| `candidate_only` | 保留原值，不自動修復，不quarantine |
| `ambiguous` | 保留原值，不選candidate，不quarantine |
| `unresolved` | 保留原值，不猜測，不quarantine |
| `unchanged_no_rule` | 保留原值，禁止fuzzy／prefix fallback |
| `not_an_error` | 由synthetic station-universe exact match補city／classification語意，不觸發repair |

## Encoding and Parquet policy

Input fixture以Base64保存每一端的原始bytes，載入時用`surrogateescape`無損還原。合法UTF-8 raw可直接顯示；非法bytes以ASCII `\xNN` escape形成serialization-safe display，Base64仍保存exact bytes。只有exact approved repair且clean string通過嚴格UTF-8時，含非法bytes的record才可進cleaned Parquet。未核准非法值不做replacement，整筆進quarantine。

本階段實際以PyArrow 21.0.0寫入Zstandard壓縮Parquet，再讀回逐record比對。`bike_type=None`、中文clean value、raw／clean並存及parser provenance均納入round-trip validation。PyArrow缺失或round-trip不一致即fail closed。

## Quarantine boundary

Quarantine不是刪除。Synthetic正常run只有1筆「非法UTF-8且未核准」因無法安全進cleaned string layer而quarantine；Tier 2、ambiguous、unresolved、unknown及not_an_error都保留在cleaned output。Quarantine保留完整安全JSON raw envelope、failure reason、source provenance、pipeline／allowlist版本與時間戳。

Allowlist mapping conflict、version mismatch、approved rule缺evidence或station ID屬partition-level契約失敗：在載入規則時整批停止，不發布任何正式partition。這和可逐record隔離的serialization failure不同。

## Atomic partition and receipt

目標partition固定模擬為`year=synthetic/month=01`。Executor先建立同層staging，完成cleaned Parquet、quarantine JSONL、record conservation、round-trip及hash後，才以單一步驟接受整個目錄；任何例外都移除staging，正式路徑不得留下半份輸出。

Run receipt記錄run／pipeline／allowlist版本、allowlist SHA-256、input hash、input／cleaned／quarantine counts、雙端repair status counts、起訖時間、output hashes、validation status與record conservation。固定synthetic timestamp下重跑兩次，receipt及output hashes完全相同。

## Synthetic result

- Input：13 records；cleaned accepted：12；quarantine：1；conservation通過。
- 雙端共24個accepted station fields：`approved_repair=5`、`candidate_only=1`、`ambiguous=1`、`unresolved=1`、`unchanged_no_rule=15`、`not_an_error=1`。
- 17種指定情境均由fixture或fail-closed rule mutation test覆蓋。
- Phase 3.3正式allowlist與evidence以SHA-256 lock test確認未被修改。

## Boundary

這是execution design與synthetic proof，不是正式cleaning policy，也不能代表真實月檔一定可成功。下一個最小任務最多是「選一個真實月份進行cleaning dry run」；本階段不執行。
