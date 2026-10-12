# Phase 3.5｜2023/11 real-month cleaning dry run

本階段只處理2023/11。選擇理由是此月已在Phase 2完成來源與schema audit，位於核心研究期間、非年節與暑假月份，並已知為6欄、無header、strict UTF-8，適合作為第一個真實月份execution驗證。它不能代表7欄或含非法UTF-8的月份。

## Source and preflight gate

- Raw ZIP：`data/raw/202311_YouBike2.0票證刷卡資料.zip`（本機保留、Git忽略）。
- ZIP bytes：34,774,679；SHA-256：`97429096d6c6a7cd227ec1209c8559d1b71e573c50be75ecdef7c67fa28b2aca`。
- CSV member：單一CSV，uncompressed 311,810,011 bytes。
- Parser：`v1_6col`、無header、2,941,065 records、`bike_type`全部structural null、parse warning 0。
- Hash、member、schema、header、筆數、缺值、encoding與duration gates均與Phase 2／3 evidence一致；任一不符即不進入final partition。

## Dry-run output

輸出位於Git忽略的`data/processed/dry_run/year=2023/month=11/`：

- `cleaned.parquet`：2,941,065 records，37,567,504 bytes（35.83 MiB）。
- `quarantine.jsonl`：0 records，0 bytes。
- `receipt.json`：run receipt；可提交副本為`notes/2023-11-cleaning-dry-run-receipt.json`。

Record conservation為`2,941,065 = 2,941,065 accepted + 0 quarantine`。`_source_row`嚴格遞增且唯一，accepted／quarantine overlap為0。原始trip欄位的order-independent雙重multiset fingerprint在preflight與Parquet reread完全相同，沒有silent loss、duplicate creation或deduplication。

## Station-side repair status

下表分母是各端2,941,065個station fields，不是trip數：

| Status | Origin | Destination |
| --- | ---: | ---: |
| `approved_repair` | 17,956 | 19,105 |
| `candidate_only` | 0 | 109 |
| `ambiguous` | 13,555 | 12,504 |
| `unresolved` | 0 | 8 |
| `unchanged_no_rule` | 2,909,554 | 2,851,781 |
| `not_an_error` | 0 | 57,558 |

Approved共37,061 station sides，占全部5,882,130 sides的0.6301%。只有approved值可讓clean station與raw station不同；逐筆Parquet reread確認未核准修改、approved缺provenance及非approved identity assignment均為0。Tier 2、ambiguous、unresolved全部保留raw值。

Tier 1 subtype（station-side counts）：

| Subtype | Applied sides |
| --- | ---: |
| 1A | 16,593 |
| 1B | 20,306 |
| 1C | 162 |

## Trip-level repair coverage

| Trip status | Records |
| --- | ---: |
| Neither side repaired | 2,905,619 |
| Origin only repaired | 16,341 |
| Destination only repaired | 17,490 |
| Both sides repaired | 1,615 |

至少一端repair共35,446 trips，占2,941,065筆的1.2052%。Station-side與trip-level counts分開回報，沒有相加混用。

## Phase 3 evidence cross-check

- Missing origin／destination：69／63，完全一致。
- Encoding：illegal UTF-8／parse-warning records皆為0，符合strict UTF-8觀察。
- Duration：`=0` 9、`>24h` 167、`>7d` 6，完全一致；只驗證既有規則，沒有filter。
- Station patterns逐端完全一致：question mark 7,420／7,539、replacement character 5,271／5,675、不平衡括號18,820／18,520、數字後綴48,504／45,215（origin／destination）。
- Repeated identical records：5,059 groups、10,160 involved records、5,101 excess copies；原始multiset fingerprint前後一致，因此所有multiplicity完整保留。沒有呼叫`drop_duplicates()`。
- Phase 3／3.1／3.3 evidence及finalized allowlist以SHA-256測試確認未修改。

## Parquet, atomicity and performance

Parquet以固定27欄schema及Zstandard寫入，完整重讀確認2,941,065 rows、全部`bike_type=null`、raw／clean並存、provenance存在且raw multiset不變。輸出SHA-256為`2212b69e57986fcc374f9f27238f9881c1bd701ae5bfd9e8aee78a9009bc1771`。

流程為preflight → staging → streaming write → reread validation → receipt → atomic finalize。正式partition在所有gate通過後才接受。CLI最後曾因Windows CP950無法顯示ZIP member的legacy-decoded字元而回報`UnicodeEncodeError`；此錯誤發生於finalize與receipt完成後，資料驗證未受影響。CLI現已改為ASCII-safe JSON輸出，沒有重跑或覆寫partition。

- Wall clock：269.10秒（包含完整preflight、cleaning/write與第一次Parquet reread）。
- Throughput：約10,929 records／秒。
- Peak working set：616,345,600 bytes（587.79 MiB，Windows process counter）。
- Input ZIP：33.16 MiB；uncompressed CSV約297.37 MiB；cleaned Parquet：35.83 MiB。

## Readiness conclusion

2023/11的6欄、strict-UTF8路徑已證明可安全執行，沒有阻止此類月份cleaning的contract問題。但**不建議直接授權2023/01–2025/03 full-period cleaning**：本月沒有實際驗證7欄／bike type及非法UTF-8月份的真實量級行為，而這兩者正是已知schema與serialization風險。較安全的下一個最小任務是再選一個同時涵蓋7欄與非法UTF-8的真實月份作bounded dry run，確認quarantine與approved illegal-byte路徑後，再決定是否全期間執行。

本階段沒有新增mapping、修改allowlist、刪除trip、去重、duration／地理篩選、OD、SNA、clustering、routing或事故整合。
