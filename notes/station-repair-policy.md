# Phase 3.2–3.3 Station repair policy and deterministic allowlist

本階段只定義修復政策、建立 deterministic allowlist 與站點 universe 重新分類；沒有修改 raw／canonical records，沒有實際 replace、cleaning、reconciliation、deduplication 或 OD construction。

## Policy outcome

| Decision | Unique raw mappings | Extended record union | Share of classified anomaly records |
| --- | ---: | ---: | ---: |
| Tier 1 — `approved_repair` | 27 | 1,114,968 | 54.4934% |
| Tier 2 — `candidate_only` | 14 | 4,377 | 0.2139% |
| Tier 3 — `ambiguous` | 12 | 926,158 | 45.2654% |
| Tier 3 — `unresolved` | 3 | 558 | 0.0273% |
| Total classified station-anomaly union | 56 raw mappings | 2,046,061 | 100% |

Phase 3.3逐筆重審29個既有approved entries時，發現同一raw bytes因`illegal_utf8`與`unbalanced_parentheses`兩條規則指向不同station ID。這2個entries（同一raw value、52 records）已fail closed降為ambiguous；最終保留27個Tier 1。Tier 1子型如下；子型record union可能在同一record同時命中，不能彼此相加：

| Tier 1 subtype | 條件 | Mappings | Affected record union |
| --- | --- | ---: | ---: |
| 1A | 唯一metadata＋dated historical snapshot＋同月／相鄰月raw temporal evidence | 8 | 611,294 |
| 1B | 唯一metadata＋dated historical snapshot；無raw temporal evidence | 6 | 471,391 |
| 1C | 唯一metadata＋同月／相鄰月raw temporal evidence；無dated snapshot | 13 | 34,350 |

1A／1B／1C都屬`approved_repair`；子型只記錄證據組合，不改變核准效力。

Record coverage 以 Phase 3 的月別 OD 聚合做 union，不直接加總每個 raw value 的 involvement count。Phase 3 正式 issue counts仍是原始分母；因另一端站名缺失而未進 OD 聚合的原生 `�` 1筆、`?` 2筆及不平衡括號7筆沒有被刪除，仍留在舊 evidence，這裡不擅自分派 decision。

## Evidence tiers

### Tier 1 — Approved deterministic repair

必須同時滿足：

1. metadata 只有一個 `(station name, station ID, city)` 候選；
2. 無競爭候選；
3. 至少一項獨立時間證據：
   - 2024/05/31 dated historical feed snapshot 存在同一 name／ID；或
   - 完整候選站名在研究期間 raw station universe 中，出現在 damaged value 的同月或相鄰月；
4. raw value、候選與證據來源均可追溯。

`approved_repair` 表示可進入未來 repair allowlist，不表示本階段已套用。

### Tier 2 — Strong candidate, insufficient evidence

metadata 候選唯一，但只有 2026 current snapshot，且完整名稱未在受損值同月／相鄰月形成歷史佐證。Decision 固定為 `candidate_only`，不得修改 records。

### Tier 3 — Ambiguous / unresolved

- 多個合理 metadata 候選：`ambiguous`。
- 無候選或證據衝突：`unresolved`。
- 不選最長名稱、不補括號、不依 fuzzy score、OD 頻率或主觀外觀選答案。

## Allowed and not allowed

| Allowed for future allowlist | Not sufficient |
| --- | --- |
| 唯一 metadata name／ID／city | current metadata alone |
| dated historical snapshot | fuzzy score alone |
| 同月／相鄰月完整 raw 名稱 | prefix alone |
| 無競爭候選 | geographic plausibility alone |
| 保存 evidence source 與版本 | most frequent OD／candidate alone |
| 規則可重跑、可 fail closed | manually choosing what “looks right” |

## Per-issue result

以下 records 是 extended report period 的 classified record union；括號內列出 mappings 數。

| Issue | Phase 3 total records | Tier 1 | Tier 2 | Ambiguous | Unresolved |
| --- | ---: | ---: | ---: | ---: | ---: |
| Illegal UTF-8 | 202,123 | 201,996（5） | 75（2） | 52（1） | 0 |
| Native `�` | 145,367 | 至少145,117（3） | 至少249（4） | 0 | 0 |
| `?` | 408,727 | 至少404,551（4） | 至少4,174（6） | 0 | 0 |
| Unbalanced / truncated | 1,294,748 | 367,958（15） | 67（2） | 926,158（11） | 558（3） |

### Historical evidence used

- 14 個 mapping 命中 2024/05/31 dated Taipei feed snapshot；其中8個也有同月／相鄰月完整 raw 名稱，6個只靠 dated snapshot 作時間佐證。
- 另13個最終approved mapping雖未命中該臺北快照，但其唯一metadata候選的完整名稱在damaged value同月／相鄰月出現，因此取得研究期間raw temporal corroboration；另2個原1C entries因跨issue identity衝突降為ambiguous。
- 其餘14個 unique current-metadata candidates 沒有上述時間證據，全部降為 Tier 2。

## Ambiguous and unresolved review

- Phase 3.1 的10個 ambiguous truncated values仍全部 ambiguous；另新增1個跨issue衝突raw value（在兩個issue下各1個mapping entry）。Machine-readable allowlist保留每個競爭候選為獨立row；沒有選最長字串、最高相似度或最常見OD。
- Phase 3.1 的3個 unresolved truncated values沒有取得新高品質證據，仍全部 unresolved。

## Destination-only reclassification policy

Destination-only 和 repair 完全分開，詳見 `notes/station-universe-classification.csv`。

| Classification | Unique names | Records | Name validity | Historical operational status |
| --- | ---: | ---: | --- | --- |
| Cross-city valid station／New Taipei | 1,311 | 1,784,172 | confirmed by exact current official name/ID | unresolved |
| Unresolved | 217 | 21,940 | unresolved | unresolved |

**Reconstruction decision：**1,311個精確命中新北官方站點的 destination-only names 設為 `not_an_error`，只代表名稱可確認且應擴張 station universe；不代表該站在歷史當月一定營運，也不產生 repair mapping。Phase 3／3.1 evidence維持原樣。

## Future repair provenance contract

正式 cleaned layer 未來至少保留：

- `origin_station_raw`
- `origin_station_clean`
- `origin_station_id`
- `origin_station_repair_status`
- `destination_station_raw`
- `destination_station_clean`
- `destination_station_id`
- `destination_station_repair_status`
- mapping rule與`rule_version`
- evidence tier與evidence source
- repair timestamp與pipeline version

禁止覆寫 raw value。Pipeline 只能 exact-match `raw_value_base64`／raw bytes 到版本化 allowlist；不在 allowlist、同時命中多條規則、證據欄空白或版本未知時必須 fail closed。

Phase 3.3已將這些欄位加入allowlist：`tier1_subtype`、`metadata_unique`、`has_historical_snapshot_evidence`、`has_temporal_raw_evidence`、`has_competing_candidate`。未來每次執行前都須重新驗證三個核心條件，不能因前一版曾標approved就自動沿用。

## Artifacts and immutability

- `config/station_repair_allowlist.csv`：56個 raw mappings；ambiguous 候選展開後共67 rows。
- `notes/station-universe-classification.csv`：1,528個 destination-only names。
- `notes/station-repair-policy-evidence.json`：tier規則、mapping與record統計、輸入證據前後SHA-256。
- `src/design_station_repair_policy.py`：只讀 Phase 3聚合與Phase 3.1 evidence，沒有 record mutation code path。

## Open questions

- 研究期間完整 official historical station master仍不可得；destination-only的歷史營運狀態繼續 unresolved。
- 正式 execution 前仍需決定 quarantine輸出、欄位型別、partition與發布流程。
