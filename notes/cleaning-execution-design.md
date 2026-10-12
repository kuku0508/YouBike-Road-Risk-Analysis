# Phase 3.3 Cleaning execution design

本文件只定義未來 station cleaning execution的安全契約。Phase 3.3沒有處理完整月檔、沒有建立cleaned trips，也沒有修改任何record。

## Final Tier 1 gate

一筆mapping只有同時滿足以下條件才可執行：

1. `metadata_unique=true`，且canonical name／ID／city只有一組；
2. `has_competing_candidate=false`；
3. `has_historical_snapshot_evidence=true`或`has_temporal_raw_evidence=true`至少一項成立；
4. `evidence_tier=Tier 1`且`tier1_subtype`為1A／1B／1C；
5. `evidence_sources`、canonical name與station ID非空；
6. allowlist `rule_version`與pipeline要求版本完全相同。

任一條件失敗即fail closed，不因舊版曾approved而保留。

## Tier 1 subtypes

- **1A：**dated historical snapshot與research-period raw temporal evidence同時存在；證據最完整。
- **1B：**dated historical snapshot存在，raw同月／相鄰月完整名稱沒有觀察到。
- **1C：**research-period raw同月／相鄰月存在完整名稱，但沒有dated historical snapshot。

三者均通過使用者指定的最低門檻。Subtype只描述證據組合；1B與1C不是靠current metadata alone。

## Execution contract

`src/station_cleaning_contract.py`提供小型、無bulk I/O的參考實作：

1. 載入指定版本allowlist；版本空白、未知或混用時停止。
2. 逐條驗證approved rule的metadata uniqueness、temporal evidence、競爭候選與provenance。
3. Runtime只把station raw value以`surrogateescape`還原成原bytes並做Base64 exact match。
4. 同一raw key若指向不同approved identities，整批fail closed。
5. 只有approved rule輸出不同的`station_clean`／`station_id`。
6. Tier 2、ambiguous、unresolved與unknown value全部保留原值。
7. 不提供fuzzy、prefix、地理或OD fallback。

未來正式欄位設計：

| Raw/provenance | Clean identity/status |
| --- | --- |
| `origin_station_raw` | `origin_station_clean` |
| raw bytes／Base64 evidence key | `origin_station_id` |
| source file／row | `origin_station_repair_status` |
| mapping evidence sources | `origin_station_rule_version` |
| pipeline version／execution timestamp | `origin_station_evidence_tier`、subtype |

Destination欄位完全同構。Raw欄永遠不可被clean值覆寫。

## Non-approved and quarantine behavior

- Tier 2：原值保留，`repair_status=candidate_only`。
- Ambiguous：原值保留，`repair_status=ambiguous`；所有candidate留在policy evidence。
- Unresolved：原值保留，`repair_status=unresolved`。
- Unknown mapping：原值保留，`repair_status=unchanged_no_rule`，不執行runtime fuzzy matching。
- Destination-only `not_an_error`：走station-universe classification，不觸發repair。

上述records不得因未修復而被刪除。它們是否納入未來OD分析，仍須由後續analysis inclusion policy另外決定。

## Versioning, revocation and rollback

- `rule_version`採不可變版本；mapping新增、修正、撤銷或evidence更新都產生新版本。
- 撤銷時在新版本標示`revoked`／`superseded`的治理狀態，不改寫舊版artifact。
- 不對歷史cleaned data原地patch；從raw source of truth配合指定新allowlist版本重新產生cleaned layer。
- 每次run保存allowlist hash、rule version、pipeline version、execution timestamp與source raw hashes。
- Rollback是以舊版allowlist及相同raw重新建置，不是逆向猜測clean值原本來自哪個raw。
- 發現衝突、缺證據或版本不存在時，不產生部分成功的cleaned partition。

## Validation boundary

目前只使用synthetic／單筆contract tests驗證1A、1B、1C、Tier 2、ambiguous、unresolved、raw保留、provenance、規則衝突、unknown mapping、數字後綴與destination-only分流。沒有執行2023/01–2025/03 full cleaning。
