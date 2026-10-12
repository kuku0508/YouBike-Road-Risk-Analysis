# Phase 2.6：YouBike raw parser contract

日期：2026-09-13。此契約只定義raw parser與小型fixture tests。它不執行資料清理、站點對照、去重、時長篩選、地理篩選、日曆分類、OD construction、SNA、clustering或routing。

## Contract outcome

任何月檔進入cleaning layer前，必須由二進位串流讀取，以實際首筆內容及每筆欄位驗證辨識為`v1_6col`或`v2_7col`，再映射成統一canonical record。未知欄寬、模糊／錯誤header、關鍵格式錯誤、未知車種或後續列schema drift一律丟出`RawParserError`子類別，不猜測、不補欄。

實作：[youbike_raw_parser.py](../src/youbike_raw_parser.py)。測試：[test_youbike_raw_parser.py](../tests/test_youbike_raw_parser.py)。fixture位於`tests/fixtures/`。

## Supported raw schemas

### `v1_6col`

| 位置 | 原始語意 | Canonical欄位 |
|---:|---|---|
| 1 | 借車時間 | `borrow_time` |
| 2 | 借車場站原值 | `origin_station_raw` |
| 3 | 還車時間 | `return_time` |
| 4 | 還車場站原值 | `destination_station_raw` |
| 5 | 借用時長原值 | `duration_raw` |
| 6 | 借用日期 | `borrow_date` |

若有header，必須精確等於：

```text
rent_time,rent_station,return_time,return_station,rent,infodate
```

`bike_type`固定映射為真正的Python `None`。不得填成`一般車`、空字串或其他推測值。

### `v2_7col`

前五欄與v1相同，第6欄映射`bike_type`，第7欄映射`borrow_date`。若有header，必須精確等於：

```text
rent_time,rent_station,return_time,return_station,rent,bike_type,infodate
```

Phase 2.5目前只觀察到`一般車`與`電輔車`。其他值代表可能的資料契約擴充，parser會fail closed，必須先人工審查及更新契約，不能自動當成新車種接受。

## Canonical schema

每筆輸出的七個業務欄位依固定順序為：

1. `borrow_time`
2. `origin_station_raw`
3. `return_time`
4. `destination_station_raw`
5. `duration_raw`
6. `bike_type`
7. `borrow_date`

值仍是未清理的原始字串；parser不轉成datetime、timedelta或category。另保留四個最小provenance欄位：

- `_source_file`：CSV檔名；ZIP輸入記為`zip::member.csv`。
- `_source_row`：CSV record序號，包含header；不是可能受quoted newline影響的實體行號。
- `_schema_version`：`v1_6col`或`v2_7col`。
- `_parse_warnings`：每筆警示清單；正常列為空list。

檔案層另以`source_sha256(path)`產生SHA-256。raw檔必須保留，hash＋`_source_file`＋`_source_row`才是回到原始證據的完整定位；canonical record本身不複製整列raw bytes。

## Schema detection gate

1. 從binary stream使用UTF-8＋`surrogateescape`讀取，並交給strict CSV parser。
2. 讀取第一個CSV record，不使用年月或檔名判斷版本。
3. 第一筆若精確等於兩個known header之一，採對應schema並跳過header。
4. 第一筆若含多個known header token、但不精確相等，判為malformed／ambiguous header並失敗。
5. 非header首筆必須恰為6或7欄，且同時通過時間、時長、日期位置及車種檢查，才可辨認schema。
6. 後續每筆必須維持同一欄寬與結構；同月中途變版會失敗。

必要格式只驗證parser結構，不做語意清理：

- `borrow_time`／`return_time`：`YYYY-MM-DD HH:MM:SS`，分鐘與秒須為00–59。
- `duration_raw`：`H+:MM:SS`，小時可超過24，分鐘與秒須為00–59。
- `borrow_date`：`YYYY-MM-DD`。
- v2 `bike_type`：目前只接受已觀察值`一般車`、`電輔車`。

parser刻意不檢查借還時間先後、時長與時間差、borrow date是否等於timestamp日期、站名是否空白或重複；這些屬於後續cleaning／品質決策。

## Encoding policy

禁止`errors="replace"`或忽略非法bytes。parser採Python `surrogateescape`：合法UTF-8正常解碼；非法byte `0x80–0xFF`一對一保留為低代理字元，必要時可用`value.encode("utf-8", "surrogateescape")`還原。

每個含非法bytes的欄位會在`_parse_warnings`記錄：

- `code=invalid_utf8_bytes`
- canonical欄位名稱
- 非法byte數量
- CSV解引號後完整field bytes的Base64

raw檔仍是最終位元組證據；Base64 sidecar用於欄位級稽核，不宣稱保存CSV原始引號或delimiter寫法。

### pandas／PyArrow／Parquet邊界

- pandas的`object`欄可能暫時容納surrogate字串，但許多UTF-8輸出操作仍可能失敗，不能視為可安全保存。
- PyArrow／Parquet的string欄要求有效UTF-8；含surrogate的Python字串不能安全直接寫入。
- `require_serialization_safe(record)`會在任何parse warning存在時丟出`UnsafeForSerializationError`。因此含非法bytes的record只能留在raw-boundary／quarantine層，不能直接進正式canonical Parquet。
- 未來若決定如何修復，須由獨立、可稽核的cleaning decision產生合法UTF-8值，並保留raw bytes與修復方法；Phase 2.6不做此決定。

## Fail-closed conditions

- 空CSV或非CSV／ZIP來源。
- ZIP不是恰好一個CSV member。
- 首筆欄寬不是6或7。
- header近似但不精確符合known header。
- 首筆無法唯一符合已知schema。
- 任一後續record欄寬改變或CSV語法錯誤。
- 時間、日期或時長格式不符。
- v2第6欄不是目前已觀察車種。
- 含非法bytes的record嘗試跨入UTF-8／Parquet資料層。

串流parser可能在檔案後段錯誤前已yield前面record；因此consumer必須寫入可丟棄的staging/quarantine，只有iterator完整到EOF且無例外時才可原子接受。不能邊parse邊把部分結果併入正式資料集。

## Parsing與cleaning責任邊界

Parser只負責：CSV／ZIP結構、schema detection、必要格式gate、canonical欄位映射、provenance與decode warning。

Parser不得：修復站名、移除`_1`、合併站點、去重、刪除缺值／異常列、篩選duration、推導行政區、判斷假日、轉成OD或修改raw內容。

## Fixture coverage

| Fixture | 預期行為 |
|---|---|
| `six_header.csv` | 偵測v1、跳header、`bike_type=None` |
| `six_no_header.csv` | 偵測v1、保留首筆 |
| `seven_header.csv` | 偵測v2、跳header |
| `seven_no_header.csv` | 偵測v2、保留首筆 |
| `invalid_utf8.csv.hex` | 無損還原非法byte、產生warning、阻止serialization |
| `unknown_width.csv` | fail closed |
| `malformed_header.csv` | fail closed |

測試另涵蓋未知車種、檔案中途欄寬改變、單CSV member ZIP、乾淨record可通過serialization gate，以及source row／schema version／原始站名不變。

## 回答完成條件

任意歷史月檔的安全流程是：**保留raw與SHA-256 → binary stream讀取 → 以首筆內容辨識header及6／7欄schema → 逐筆結構驗證 → 映射未清理canonical欄位與provenance → decode warning列留在quarantine → 全檔成功到EOF後才可交給cleaning layer。**

Phase 2.6到此停止，不進入正式cleaning或Phase 3。
