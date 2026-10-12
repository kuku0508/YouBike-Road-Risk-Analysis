# Phase 3.6｜2024/11 adversarial real-month cleaning dry run

本階段只處理2024/11，專門驗證7欄、真實bike type與非法UTF-8的execution path。它是full-period cleaning前最後一個預定dry run；沒有處理其他月份，也沒有執行OD、network、SNA、clustering、routing或事故整合。

## Source and preflight

- Raw ZIP：`data/raw/202411_YouBike2.0票證刷卡資料.zip`（本機保留、Git忽略）。
- ZIP：70,942,022 bytes；SHA-256 `a255acf386d88fbb1429147b87c257017c4cff1f851b3860ded61ad3894bc20a`。
- 單一CSV member：685,207,045 uncompressed bytes。
- Parser：5,883,102 records、`v2_7col`、無header；column 6為bike type、column 7為borrow date。
- Bike type：一般車5,733,169；電輔車149,933；blank／null 0；unknown 0。
- Source hash、member、筆數、schema、header、bike type、encoding、missing、duration及station patterns全部與Phase 2.5／3 evidence一致。

## Illegal UTF-8 acceptance target

| Metric | Count |
| --- | ---: |
| Illegal bytes | 25,720 |
| Affected station fields／sides | 20,944 |
| Affected records | 20,217 |
| Origin affected sides | 10,029 |
| Destination affected sides | 10,915 |
| Both endpoints affected trips | 727 |
| Unique raw Base64 pattern union | 7 |

Illegal station-side disposition：origin 10,029 sides全部為Tier 1 approved；destination為approved 10,901、candidate-only 3、ambiguous 11。沒有illegal unresolved或unchanged-no-rule。

- Approved illegal-byte repair：20,930 station sides／20,203 records成功進入cleaned Parquet；canonical name、ID、city、rule version、evidence tier與subtype完整。
- Unapproved illegal-byte：14 destination sides／14 records整筆quarantine，其中Tier 2 candidate-only 3、ambiguous 11。
- Quarantine原因全為`serialization_unsafe_unapproved_destination_station_raw`；涉及2個unique raw Base64 patterns。
- 原始bytes以Base64保留，serialization-safe raw display只用`\\xNN`呈現；exact match與multiset identity均由Base64還原bytes，沒有使用Unicode replacement。

## Record outcomes

`5,883,102 input = 5,883,088 accepted + 14 quarantine`，quarantine rate為0.000238%。每個`_source_row`只對應一個outcome，accepted與quarantine不重疊。

Input bike type亦分母分離：accepted為一般車5,733,157／電輔車149,931；quarantine為一般車12／電輔車2；兩者相加回到完整input分布。

### Station-side repair status

下表分母是各端5,883,088個accepted station fields，不是trip數：

| Status | Origin | Destination |
| --- | ---: | ---: |
| `approved_repair` | 35,063 | 36,512 |
| `candidate_only` | 0 | 185 |
| `ambiguous` | 34,266 | 32,228 |
| `unresolved` | 0 | 0 |
| `unchanged_no_rule` | 5,813,759 | 5,735,096 |
| `not_an_error` | 0 | 79,067 |

Approved合計71,575 station sides，占完整input 11,766,204 sides的0.6083%。Serialization-safe的candidate-only、ambiguous與unknown均保留raw值；destination-only `not_an_error`不修復、不刪除。

### Trip-level repair counts

| Outcome | Accepted trips |
| --- | ---: |
| Neither side repaired | 5,814,204 |
| Origin only repaired | 32,372 |
| Destination only repaired | 33,821 |
| Both sides repaired | 2,691 |

至少一端repair為68,884 accepted trips，占完整input的1.1709%。

Tier 1 subtype（station-side counts）：1A 42,371；1B 24,318；1C 4,886，合計71,575。

## Repeated records and Phase 3 cross-check

- Repeated groups 17,918；involved records 36,264；excess copies 18,346。
- Multiplicity：2次17,587組、3次283組、4次23組、5次以上25組。
- Accepted與quarantine fingerprint合併後，完全等於input raw-record multiset fingerprint；沒有row loss、duplicate creation或deduplication。
- Missing origin／destination為0／1；duration `=0` 6、`>24h` 464、`>7d` 28。
- Station patterns與Phase 3一致：question mark origin 12,164／destination 12,332；不平衡括號47,136／45,722；數字後綴93,362／88,508。原生replacement character皆0。
- Phase 3、3.1、3.3 evidence及allowlist hash保持不變。

## Parquet, quarantine, atomicity and receipt

- Cleaned Parquet：5,883,088 rows、79,987,492 bytes（76.28 MiB）；SHA-256 `5a9dfe41c73a5b1b59948331998dbc7f820258376eea31d119ede8cbe5ef9a0e`。
- Quarantine JSONL：14 rows、19,822 bytes（19.36 KiB）；SHA-256 `bd1774c2569feb2faaeb5c2374fbc06352cea85ca35d1e326087368ec279a970`。
- 完整Parquet reread驗證bike type、Base64 raw evidence、provenance、repair metadata與combined multiset fingerprint。
- 非approved clean變更、approved缺provenance、非approved identity assignment皆為0。
- Receipt位於partition內；可提交副本為`notes/2024-11-cleaning-dry-run-receipt.json`。

第一次執行在finalize前正確fail closed：驗證器誤把完整input bike-type分布要求於排除14筆quarantine後的accepted Parquet。Phase 3.5因quarantine=0沒有暴露此denominator defect。正式partition與receipt均未留下。最小修正後，input／accepted／quarantine bike-type counts分開驗證，並加入一筆accepted＋一筆quarantine的regression test；第二次完整run才atomic finalize。

## Performance

- Wall clock：601.63秒（10.03分鐘；包含preflight、cleaning/write與Parquet reread）。
- Throughput：約9,779 input records／秒。
- Peak working set：630,452,224 bytes（601.25 MiB）。
- Raw ZIP：67.66 MiB；uncompressed CSV：653.46 MiB；cleaned Parquet：76.28 MiB；quarantine：19.36 KiB。

## Full-period readiness

2023/11已驗證6欄、structural-null及strict UTF-8；2024/11已驗證7欄、一般車／電輔車、非法UTF-8、approved repair、未核准quarantine、Parquet、record conservation與repeated preservation。兩月均與既有evidence一致，沒有仍可能造成silent corruption的execution bug。

**FULL-PERIOD CLEANING: READY**

下一個最小任務只能是：執行2023/01–2025/03 full-period cleaning。本階段沒有自行開始。
