# Phase 3：YouBike 全期間 data quality profile

> **Observed in raw data**：本文件只描述2023/01–2024/12官方月檔的完整唯讀掃描結果；不代表原研究採用相同檔案版本或處理方式。

> **Reconstruction decision**：本階段未清理、修復、刪列、去重、站點reconciliation或建立OD。Repeated identical records全部保留。

## 範圍與方法

- 核心期間：2023/01–2024/12，共24個官方月檔。CSV精確header不列入分母；所有data records均保留，總計 **92,700,026 records**。本階段未另以逐日筆數判定交易完整性。
- 以Phase 2.6 content-based parser contract辨識6／7欄及header；UTF-8以`surrogateescape`無損解碼。
- 欄位值採raw exact match；未trim、normalize、修復、fuzzy match或站點ID回填。
- `rare_od_pair`的描述性定義：同一raw origin/destination組合在整個核心期間僅出現1次。這不是錯誤判定。
- `destination_only_station`以核心全期非空raw名稱判定，而不是逐月判定。

## 最終狀態

```text
Total records                                92,700,026  100.0000%
├── Invalid union                                    0  0.0000%
├── Quality-issue union                      1,878,361  2.0263%
├── Suspicious union                         1,870,420  2.0177%
└── Clean-with-respect-to-current-rules     88,977,863  95.9847%

Repeated identical records (retained)          637,221  0.6874%
```

Invalid／Quality／Suspicious並非互斥。`Clean-with-respect-to-current-rules`只代表沒有命中本次規則，不等於已清理或已證實正確。Repeated identical records獨立報告，不改變上述分類。

## Issue摘要

| Issue | Category | Records | % | Unique raw values | Main months | Status |
|---|---:|---:|---:|---:|---|---|
| 檔案首列schema／header無法安全辨識 | Invalid | 0 | 0.0000% | — | — | investigate |
| 列欄寬不符 | Invalid | 0 | 0.0000% | — | — | investigate |
| 借車時間無效 | Invalid | 0 | 0.0000% | — | — | investigate |
| 還車時間無效 | Invalid | 0 | 0.0000% | — | — | investigate |
| duration格式無效 | Invalid | 0 | 0.0000% | — | — | investigate |
| 借用日期無效 | Invalid | 0 | 0.0000% | — | — | investigate |
| 7欄版不支援車種 | Invalid | 0 | 0.0000% | — | — | investigate |
| origin station缺失 | Quality issue | 272 | 0.0003% | — | 2023-01 (105), 2023-12 (78), 2023-11 (69) | investigate |
| destination station缺失 | Quality issue | 397 | 0.0004% | — | 2023-01 (109), 2023-12 (88), 2023-11 (63) | investigate |
| 含非法UTF-8 byte | Quality issue | 181,703 | 0.1960% | 11 | 2024-12 (22,953), 2024-08 (22,643), 2024-11 (20,217) | investigate |
| 站名含U+FFFD `�` | Quality issue | 145,367 | 0.1568% | 7 | 2024-05 (15,775), 2024-06 (14,126), 2024-04 (13,696) | investigate |
| 站名含`?` | Quality issue | 342,114 | 0.3691% | 10 | 2024-12 (26,271), 2024-08 (23,718), 2024-11 (23,669) | investigate |
| 站名括號不平衡 | Quality issue | 1,213,059 | 1.3086% | 31 | 2024-12 (101,530), 2024-11 (90,251), 2024-08 (86,576) | investigate |
| duration = 0 | Suspicious | 362 | 0.0004% | — | 2023-05 (114), 2023-07 (32), 2023-06 (19) | retain |
| duration > 24h | Suspicious | 6,988 | 0.0075% | — | 2024-10 (632), 2024-09 (564), 2024-08 (488) | retain |
| duration > 7d（含於>24h） | Suspicious | 602 | 0.0006% | — | 2024-10 (51), 2024-01 (42), 2023-09 (39) | retain |
| 還車時間早於借車時間 | Suspicious | 0 | 0.0000% | — | — | retain |
| duration與整點時間差相差≥1h | Suspicious | 231 | 0.0002% | — | 2023-07 (51), 2023-06 (28), 2023-05 (25) | retain |
| destination-only station | Suspicious | 1,564,493 | 1.6877% | 1460 | 2024-12 (87,122), 2024-08 (83,339), 2024-11 (80,010) | retain |
| 全期只出現1次的raw OD pair | Suspicious | 299,458 | 0.3230% | — | 2024-12 (22,084), 2024-11 (20,100), 2024-08 (15,580) | retain |
| 完全相同record（另列、全保留） | Repeated / retained | 637,221 | 0.6874% | — | 2024-12, 2024-10, 2024-09 | retain |

## Encoding profiling

- Illegal byte count：**229,167**。
- Affected field count：**189,089**。
- Affected record count：**181,703（0.1960%）**。
- Origin affected records：91,914；destination：97,175；同筆多欄受影響：7,386。
- 非法bytes僅出現在`origin_station_raw`與`destination_station_raw`。完整掃描首次顯示受影響月份為2023/03–07與2024/07–12；這擴充了Phase 2.5代表月份抽樣的觀察範圍。

| Field | Illegal bytes | Affected fields | Affected records |
|---|---:|---:|---:|
| `destination_station_raw` | 118,545 | 97,175 | 97,175 |
| `origin_station_raw` | 110,622 | 91,914 | 91,914 |

`illegal bytes ≠ affected fields ≠ affected records`；上述數字不可互換。沒有執行encoding repair。

## Station-field profiling

- Origin missing：272；destination missing：397；任一端missing：661；兩端皆missing：8。
- 含`�`：145,367 records／7種raw值。含`?`：342,114／10種。括號不平衡：1,213,059／31種。
- Destination-only：1,564,493 records、1,460種raw名稱。這可能包含跨市還車或名稱品質問題，尚未做站點主檔比對。
- `_數字`後綴共有16種raw名稱；origin side occurrences 1,526,624、destination side occurrences 1,437,286。僅盤點，不視為error。

## Duration與時間關係

| Statistic | Seconds | H:MM:SS |
|---|---:|---:|
| P50 | 551 | 0:09:11 |
| P90 | 1,890 | 0:31:30 |
| P95 | 3,082 | 0:51:22 |
| P99 | 7,154 | 1:59:14 |
| P99.9 | 15,759 | 4:22:39 |
| max | 315,533,802 | 87648:16:42 |

- 可解析duration：92,700,026；duration=0：362；>24h：6,988；>7d：602。極端值全部保留。
- 跨午夜候選：348,404，僅描述、不列issue。借還整點完全相同：71,371,800，符合已知整點精度限制，不列issue。
- 還車早於借車：0；duration與整點時間差相差≥1h：231，列Suspicious但保留。

## Bike type

- 6欄schema structural absence：80,305,284 records；不算missing-data error。
- 7欄schema：一般車 12,049,793；電輔車 344,949；blank/null 0；unknown 0。

## Repeated identical records（獨立報告、全部保留）

- Repeated groups：**316,265**。
- Involved records：**637,221（0.6874%）**。
- Excess copies：**320,956**。這是multiplicity統計，不是應刪列數。
- Multiplicity groups：2次 312,350；3次 3,237；4次 617；5次以上 61。

> 這只是 repeated-record profiling，不代表錯誤旅次。歷史資料沒有trip ID，且借還時間只有整點精度；本專案正式決策為全部保留，不執行`drop_duplicates()`。

## 類別重疊

| Records | Invalid | Quality issue | Suspicious |
|---|---:|---:|---:|
| Invalid | 0 | 0 | 0 |
| Quality issue | 0 | 1,878,361 | 26,618 |
| Suspicious | 0 | 26,618 | 1,870,420 |

Quality∩Suspicious為26,618 records。至少命中一個issue的record union為3,722,163；不能以各issue count直接相加。完整issue-by-issue cross-count見JSON。

## 月別摘要

| Month | Records | Schema/header | Invalid | Quality | Suspicious | Encoding affected | Repeated involved |
|---|---:|---|---:|---:|---:|---:|---:|
| 2023-01 | 2,686,167 | v1_6col / header | 0 | 45,648 (1.6994%) | 68,345 (2.5443%) | 0 | 13,129 |
| 2023-02 | 2,837,717 | v1_6col / header | 0 | 55,195 (1.9450%) | 68,995 (2.4314%) | 0 | 13,849 |
| 2023-03 | 3,774,370 | v1_6col / header | 0 | 69,914 (1.8523%) | 90,423 (2.3957%) | 12,234 | 19,367 |
| 2023-04 | 3,365,049 | v1_6col / header | 0 | 64,074 (1.9041%) | 90,127 (2.6783%) | 11,516 | 17,115 |
| 2023-05 | 3,641,896 | v1_6col / header | 0 | 69,118 (1.8979%) | 87,225 (2.3950%) | 12,343 | 17,985 |
| 2023-06 | 3,362,023 | v1_6col / no header | 0 | 62,199 (1.8500%) | 74,418 (2.2135%) | 11,608 | 16,554 |
| 2023-07 | 3,055,147 | v1_6col / no header | 0 | 56,352 (1.8445%) | 70,943 (2.3221%) | 11,038 | 12,790 |
| 2023-08 | 2,722,839 | v1_6col / no header | 0 | 52,097 (1.9133%) | 59,956 (2.2020%) | 0 | 10,454 |
| 2023-09 | 2,863,438 | v1_6col / no header | 0 | 56,758 (1.9822%) | 65,654 (2.2928%) | 0 | 10,643 |
| 2023-10 | 2,843,257 | v1_6col / no header | 0 | 59,350 (2.0874%) | 67,927 (2.3891%) | 0 | 10,290 |
| 2023-11 | 2,941,065 | v1_6col / no header | 0 | 61,202 (2.0809%) | 68,730 (2.3369%) | 0 | 10,160 |
| 2023-12 | 2,725,874 | v1_6col / no header | 0 | 56,912 (2.0878%) | 59,893 (2.1972%) | 0 | 9,484 |
| 2024-01 | 2,746,557 | v1_6col / no header | 0 | 56,173 (2.0452%) | 62,036 (2.2587%) | 0 | 9,628 |
| 2024-02 | 2,590,755 | v1_6col / no header | 0 | 52,266 (2.0174%) | 64,633 (2.4948%) | 0 | 11,317 |
| 2024-03 | 3,472,416 | v1_6col / no header | 0 | 70,907 (2.0420%) | 72,883 (2.0989%) | 0 | 13,208 |
| 2024-04 | 3,798,550 | v1_6col / no header | 0 | 65,232 (1.7173%) | 78,377 (2.0633%) | 0 | 15,880 |
| 2024-05 | 4,338,453 | v1_6col / no header | 0 | 77,718 (1.7914%) | 84,945 (1.9580%) | 0 | 17,098 |
| 2024-06 | 3,773,353 | v1_6col / no header | 0 | 71,355 (1.8910%) | 68,949 (1.8273%) | 0 | 15,304 |
| 2024-07 | 5,528,656 | v1_6col / no header | 0 | 117,335 (2.1223%) | 86,915 (1.5721%) | 19,756 | 40,532 |
| 2024-08 | 6,180,179 | v1_6col / no header | 0 | 132,532 (2.1445%) | 99,336 (1.6073%) | 22,643 | 48,924 |
| 2024-09 | 5,799,896 | v1_6col / no header | 0 | 124,805 (2.1518%) | 84,733 (1.4609%) | 19,535 | 52,368 |
| 2024-10 | 5,257,627 | v1_6col / no header | 0 | 117,033 (2.2260%) | 84,985 (1.6164%) | 17,860 | 89,399 |
| 2024-11 | 5,883,102 | v2_7col / no header | 0 | 133,823 (2.2747%) | 100,443 (1.7073%) | 20,217 | 36,264 |
| 2024-12 | 6,511,640 | v2_7col / no header | 0 | 150,363 (2.3091%) | 109,549 (1.6824%) | 22,953 | 125,479 |

## 主要風險與解讀

1. 站名括號不平衡影響1,213,059 records，是最大Quality flag；31種raw名稱多呈現被截短的字串外觀，但原因及正確名稱仍未證實。
2. Destination-only影響1,564,493 records，是最大Suspicious flag；未完成跨市站點與歷史station master reconciliation前，不能把它判成錯誤。
3. `?`、原生`�`與非法UTF-8是三種不同現象，分別影響342,114、145,367與181,703 records，彼此可能重疊；不能用單一replace規則處理。
4. 極端duration的max遠高於24小時，但只有6,988 records >24h；極端不等於錯誤，需先決定duration與整點timestamp矛盾時的優先欄位。
5. 637,221 records位於完全相同record群組，但沒有trip ID足以證明重複匯入；全部保留。

## Unresolved cleaning questions（本階段不決定）

- 非法UTF-8、原生`�`、`?`與截短站名應採quarantine、保留raw label，或以哪一份可追溯歷史station master修復？
- Destination-only raw名稱中，哪些是合法跨市還車、歷史更名／移站，哪些才是名稱損壞？
- OD節點納入前，origin/destination缺失records的處理與denominator如何定義？
- 極端duration與整點timestamp不一致時，以哪個欄位為權威？是否需要只做敏感度分析而非刪除？
- Rare OD與repeated identical records應如何在後續診斷中保留標記，而不改變旅次權重？

## Validation

- PASS：24 monthly file counts sum to total_records。
- PASS：category combinations are exhaustive and sum to total_records。
- PASS：all monthly totals and clean counts are internally consistent。
- PASS：illegal bytes, affected fields, affected records, and monthly affected records reconcile。
- PASS：repeated groups + excess copies = involved records; retain_all policy present。
- PASS：v1 structural absence plus v2 bike-type counts equals total_records。
- PASS：profile declares no cleaning and no duplicate removal。
- PASS：all 24 ZIP byte sizes match the saved official HEAD receipt。
- PASS：extended: 27 monthly file counts sum to total_records。
- PASS：extended: category combinations are exhaustive and sum to total_records。
- PASS：extended: all monthly totals and clean counts are internally consistent。
- PASS：extended: illegal bytes, affected fields, affected records, and monthly affected records reconcile。
- PASS：extended: repeated groups + excess copies = involved records; retain_all policy present。
- PASS：extended: v1 structural absence plus v2 bike-type counts equals total_records。
- PASS：extended: profile declares no cleaning and no duplicate removal。
- PASS：extended: all 27 ZIP byte sizes match the saved official HEAD receipt。
- 合成fixture與既有parser/audit tests另行驗證；raw ZIP與SQLite中間檔均由`.gitignore`排除。


## Extended report period 補充（2023/01–2025/03）

> **Observed in raw data**：以下為同一套Phase 3規則對27個月重新計算的結果。Core period仍保留在本文件前半與JSON根層，沒有被extended denominator覆蓋。

| Period | Total records | Invalid union | Quality union | Suspicious union | Clean under current rules |
|---|---:|---:|---:|---:|---:|
| Core 2023/01–2024/12 | 92,700,026 | 0 (0.0000%) | 1,878,361 (2.0263%) | 1,870,420 (2.0177%) | 88,977,863 (95.9847%) |
| Extended 2023/01–2025/03 | 109,713,899 | 0 (0.0000%) | 2,046,728 (1.8655%) | 2,132,663 (1.9438%) | 105,562,684 (96.2163%) |

新增2025/01–03共 **17,013,873 records**。`destination_only_station`與`rare_od_pair`依各自全期間重新判定，因此extended union不能由core union直接加上三個月union。

### 2025/01–03 月別結果

| Month | Records | Schema/header | Invalid | Quality | Suspicious | Encoding affected | Repeated involved |
|---|---:|---|---:|---:|---:|---:|---:|
| 2025-01 | 5,552,541 | v2_7col / no header | 0 | 124,391 (2.2403%) | 96,261 (1.7336%) | 20,420 | 32,724 |
| 2025-02 | 5,252,701 | v2_7col / no header | 0 | 20,522 (0.3907%) | 89,094 (1.6962%) | 0 | 95,265 |
| 2025-03 | 6,208,631 | v2_7col / no header | 0 | 23,454 (0.3778%) | 113,445 (1.8272%) | 0 | 37,950 |

### 新行為檢查

- **Schema：沒有觀察到新行為。** 2025/01、02、03皆為`v2_7col`、無header，全月未命中Invalid schema gate。
- **Bike type：沒有新值。** 新增月份只有一般車 16,394,951、電輔車 618,922；blank／unknown均為0。
- **Encoding：沒有新欄位或新raw byte value；既有問題在2025/01持續。** 新增 25,664 illegal bytes、21,178 affected fields、20,420 affected records；2025/02–03為0。
- **Station anomaly pattern：沒有新pattern class或新raw anomaly value。** 2025/01新增既有括號不平衡81,689 records；三個月合計既有`?` 66,613 records；原生`�`新增0。`_數字`後綴仍只盤點、不視為error。
- **Duration／temporal：沒有新異常型態，長尾比率略低。** 新增duration=0共1、>24h 868、>7d 50、timestamp差異≥1h 12、return-before-borrow 0；跨午夜候選43,994。

| Duration statistic | Core seconds | Extended seconds |
|---|---:|---:|
| P50 | 551 | 543 |
| P90 | 1,890 | 1,839 |
| P95 | 3,082 | 2,990 |
| P99 | 7,154 | 6,999 |
| P99.9 | 15,759 | 15,502 |
| max | 315,533,802 | 315,533,802 |

Extended repeated identical records：397,971 groups、803,160 involved records、405,189 excess copies；全部保留。

### Extended validation

- PASS：27個月份均以相同Phase 3規則完整重算。
- PASS：core denominator與既有92,700,026 records統計保留於JSON根層。
- PASS：2025/01–03 raw ZIP未納入Git；沒有產生cleaned records。

Phase 3範圍補充到此停止。沒有制定或執行cleaning policy，也未進入Phase 3.1／Phase 4。
