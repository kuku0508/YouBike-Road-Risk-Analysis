# Phase 2.5：YouBike 歷史 schema compatibility 與站點 metadata 盤點

日期：2026-09-13。範圍只包含唯讀下載、schema／encoding 相容性檢查，以及站點 metadata discovery；沒有正式 cleaning、欄位轉換、站名合併、OD matrix、SNA、clustering、routing 或事故整合。

## 結論

**歷史月檔至少存在兩種資料 schema、兩種 header 狀態，以及一種局部非法 UTF-8 狀態。** 已掃描的2024/10仍為6欄；2024/11已為7欄且第6欄是`一般車`／`電輔車`，因此在「月份檔案」粒度上，觀察到的schema transition介於2024/10與2024/11，第一個已確認7欄月份是2024/11。這不能證明實際上游系統在11月1日切換，也不能推定未下載月份的內容。

正式parser至少必須支援：6欄有header、6欄無header、7欄有header、7欄無header；另須以保留原始位元組的方式處理局部非法UTF-8，不能全域套用目前7欄metadata或用取代字元靜默解碼。

目前官方即時站點資料具有station ID、名稱、行政區、地址與經緯度，但沒有`valid_from`／`valid_to`。找到一份第三方保存的2024/05/31官方即時資料快照，可提供當日站點對照；仍未找到涵蓋2023–2024且能標明更名／移站有效期間的完整官方historical station master。

## 證據標籤

- **Report-specified**：原報告使用2023–2024租借紀錄建立OD；未列不同月份的schema版本或parser規則。
- **Current official metadata**：政府資料開放平臺目前備註的月份欄序為借車時間、借車場站、還車時間、還車場站、借用時長、車種、借用日期。這是目前頁面內容，不回溯套用歷史月檔。
- **Observed in raw data**：下表是指定月份ZIP內全部CSV列的實際欄寬與格式掃描結果。
- **Reconstruction decision**：parser先做schema gate，依實際header、欄寬與值型態判讀版本；非法位元組保留並報錯／隔離，不能靜默替換。
- **Assumption**：7欄新增與YouBike 2.0E相關是合理線索，但本次沒有找到官方變更公告直接證明發布端schema切換原因，因此不把原因寫成已確認事實。

## Current official metadata

[政府資料開放平臺租借紀錄頁](https://data.gov.tw/dataset/150635)目前明列7欄順序，頁面顯示詮釋資料更新時間為2026-04-17。該頁的主要欄位區描述的是source index六欄，備註才描述每月旅次檔七欄；兩層資料不可混用。

官方目前描述：

1. 借車時間
2. 借車場站
3. 還車時間
4. 還車場站
5. 借用時長
6. 車種
7. 借用日期

## Schema compatibility matrix

每個月份均下載完整ZIP並掃描ZIP內全部CSV列；row count包含header（若存在）。`格式不符資料列`已扣除已辨認的header。時間格式均為`YYYY-MM-DD HH:MM:SS`，借用時長均符合`H+:MM:SS`，解讀單位一致為時、分、秒。

| 月份 | CSV列數 | Header | 全檔欄寬 | 第6欄 | 第7欄 | 車種欄 | 日期位置 | Decode狀態 | 非法UTF-8 bytes | 格式不符資料列 |
|---|---:|---|---:|---|---|---|---:|---|---:|---:|
| 2023/01 | 2,686,168 | 有，6欄英文header | 6 | 借用日期 | 不存在 | 無 | 6 | UTF-8 strict | 0 | 0 |
| 2023/11 | 2,941,065 | 無 | 6 | 借用日期 | 不存在 | 無 | 6 | UTF-8 strict | 0 | 0 |
| 2024/01 | 2,746,557 | 無 | 6 | 借用日期 | 不存在 | 無 | 6 | UTF-8 strict | 0 | 0 |
| 2024/06 | 3,773,353 | 無 | 6 | 借用日期 | 不存在 | 無 | 6 | UTF-8 strict | 0 | 0 |
| 2024/09 | 5,799,896 | 無 | 6 | 借用日期 | 不存在 | 無 | 6 | UTF-8＋surrogateescape | 24,407 | 0 |
| 2024/10 | 5,257,627 | 無 | 6 | 借用日期 | 不存在 | 無 | 6 | UTF-8＋surrogateescape | 22,268 | 0 |
| 2024/11 | 5,883,102 | 無 | 7 | 一般車／電輔車 | 借用日期 | 有 | 7 | UTF-8＋surrogateescape | 25,720 | 0 |
| 2024/12 | 6,511,640 | 無 | 7 | 一般車／電輔車 | 借用日期 | 有 | 7 | UTF-8＋surrogateescape | 28,756 | 0 |
| 2025/03 | 6,208,631 | 無 | 7 | 一般車／電輔車 | 借用日期 | 有 | 7 | UTF-8 strict | 0 | 0 |
| 2026/07 | 7,596,993 | 有，7欄英文header | 7 | 一般車／電輔車 | 借用日期 | 有 | 7 | UTF-8 strict | 0 | 0 |

固定計算證據見[schema-compatibility-evidence.json](schema-compatibility-evidence.json)，下載URL與raw hash見[schema-source-receipt.json](schema-source-receipt.json)，可重跑程式見[audit_schema_compatibility.py](../src/audit_schema_compatibility.py)。

### 實際header與資料形狀

- 2023/01 header：`rent_time,rent_station,return_time,return_station,rent,infodate`。
- 2026/07 header：`rent_time,rent_station,return_time,return_station,rent,bike_type,infodate`。
- 6欄資料例的第6欄為`2024-10-17`；7欄資料例的第6／7欄為`電輔車,2024-11-15`。
- 各檔所有列欄寬固定，沒有同一月混合6欄與7欄。
- 有header並不是依年份固定：2023/01有、2023/11沒有；2026/07再度有。parser不能一律設定`header=None`或一律吃掉首列。

### Encoding相容性

2024/09–2024/12不能以嚴格UTF-8完整解碼；各檔分別觀察到22,268–28,756個不可解碼bytes。audit以Python `surrogateescape`一對一保留這些bytes後解析CSV，沒有用`errors=replace`創造新的`�`，且全部資料列仍通過欄寬、時間、時長與日期位置檢查。

這只確認檔內有局部非法UTF-8，不確認造成原因，也不代表整檔是CP950。相同樣本無法嚴格CP950解碼。正式parser應保存raw bytes、記錄受影響列與欄位，並把文字修復留給後續有證據的規則。

## Schema transition 結論

- **Observed in raw data**：2024/10為6欄；2024/11為7欄。
- **Observed in raw data**：車種欄在第一個已確認7欄月2024/11出現，值為`一般車`與`電輔車`。
- **Reconstruction interpretation**：對這份source index的月檔，parser版本邊界可暫以`<=2024-10`候選6欄、`>=2024-11`候選7欄規劃，但每個檔案仍須實際schema gate，不能只信月份。
- **Assumption**：不能由月檔判定欄位是在2024/11/01精確上線，亦未證實是因2.0E上線而改版。

## Historical station metadata discovery

### 可用來源

1. **Current official metadata／snapshot**：[臺北市資料大平臺](https://data.taipei/dataset/detail?id=c6bc8aed-557d-41d5-bfb1-8da24f78f2fb)說明目前即時JSON包含`sno`、`sna`、`sarea`、`ar`、`latitude`與`longitude`。2026/09/13取得的官方即時快照有1,800列，這六個核心欄位均無缺失，快照內ID及名稱各自唯一；但沒有有效期間。
2. **Historical point snapshot／third-party preservation**：[LittleFish-Coder/youbike-info-collector](https://github.com/LittleFish-Coder/youbike-info-collector/tree/master/result)保存2024/05/16–2024/06/01的每日檔。本次檢查2024/05/31，含1,415個站點的ID、名稱、行政區、地址、經緯度，核心欄位無缺失且快照內ID及名稱各自唯一；它是第三方保存的官方feed快照，不是官方historical station master。
3. **非本研究期的較舊archive**：[bdon/youbike-forecast](https://github.com/bdon/youbike-forecast)聲明保存2015/01/24–08/22的API回應，時間早於本研究核心期，不能補足2023–2024。

未找到具有`valid_from`、`valid_to`或完整更名／移站事件的官方歷史站表。政府平臺上另有一筆「歷史設置量與使用量統計」的[資料開放建議](https://data.gov.tw/suggests/136931)，其頁面是建議／回應紀錄，不能當作資料集已存在的證據。

### 跨快照穩定性

2024/05/31與2026/09/13兩快照共有1,411個station ID：1,398個名稱相同、13個名稱不同、31個經緯度字串不同；舊快照另有4個ID、新快照另有389個ID。這證明單一目前快照不足以回填所有歷史屬性；兩個端點快照也無法判定更名或移站發生日期。

### Phase 2問題名稱 matching feasibility

這裡只做exact-string probe，沒有合併或改名。目前官方`sna`只移除固定前綴`YouBike2.0_`後比較。

| Phase 2候選類型 | 名稱數 | 2024/05/31 exact match | 2026/09/13 exact match | 判讀 |
|---|---:|---:|---:|---|
| 含`�` | 6 | 0 | 0 | 需要原始bytes或其他歷史來源，不能猜字 |
| 含`?` | 7 | 0 | 0 | 不能自動替換 |
| 括號不平衡 | 17 | 0 | 0 | 可能損壞／截斷，原因未確認 |
| `_數字`後綴 | 16 | 16 | 16 | 後綴名稱在站點快照中真實存在 |
| destination-only | 958 | 0 | 0 | 臺北站點快照不足；可能含跨市或損壞名稱，但未證實分類 |

16個後綴名稱中，有14個在兩個快照中同時存在無後綴base名稱，而且兩者對應不同station ID。這是**禁止直接移除後綴**的明確證據，不是正式reconciliation規則。完整ID配對與來源hash見[station-metadata-evidence.json](station-metadata-evidence.json)，重跑程式見[audit_station_metadata.py](../src/audit_station_metadata.py)。

## Parser compatibility requirements

正式cleaning前，讀取層至少應：

1. 先檢查ZIP member、encoding、首列值型態與每列欄寬，再決定schema；不以檔名月份作唯一判斷。
2. 支援6欄版：`rent_time, origin_name, return_time, destination_name, duration, date`。
3. 支援7欄版：上述前5欄＋`bike_type, date`。
4. 分別支援有／無英文header，並驗證header內容；不能固定跳過第一列。
5. 對局部非法UTF-8保留原始bytes及列位置並產生品質警示；禁止靜默replacement。
6. 驗證全檔欄寬一致、時間／時長／日期格式及6／7欄位置；遇到未知版本fail closed，不自行補欄。
7. 將schema parsing與station reconciliation分層；parser只保留原值，不在讀取時改名或刪列。

以上是相容性需求，不是已執行的正式cleaning pipeline。

## Unresolved issues

- 2024/10與2024/11月檔之間的發布端精確切換日期與原因未知。
- 2024/09–12非法UTF-8的來源、受影響站名原字與官方修復方法未知。
- source index中未抽樣月份的header與encoding狀態未知；即使可用月份界線規劃兩版parser，仍需逐檔schema gate。
- 尚無完整2023–2024官方historical station master及有效期間。
- destination-only名稱的跨市比例與可用的新北市歷史站點來源尚未盤點。
- 兩個站點快照之間13個改名與31個座標差異的確切生效日期未知。

## Validation

- 10個月份共49,405,032個CSV records完成全檔欄寬與格式掃描；扣除兩列已辨認header後，所有資料列符合各自6／7欄schema。
- ZIP CRC讀至EOF、下載bytes／hash與raw檔重跑前後指紋一致。
- 10個合成測試通過，涵蓋6／7欄、有／無header、非法UTF-8保存、時長不跨24小時回捲、站點ID／名稱衝突與非破壞性matching。
- raw月檔、官方即時快照、第三方站點快照都在`data/raw/`且被Git忽略；固定小型evidence與程式才納入Git。
- 沒有建立清理後資料、OD、graph、分群或路由結果。

建議下一個最小任務：**Phase 2.6 parser contract與只讀fixture測試設計**。先把上述四種header／欄寬組合、非法UTF-8處理與fail-closed條件寫成資料契約及小型fixture；不要立刻跑正式全量cleaning，也不要進入OD construction。

Phase 2.5到此停止，不進入Phase 3。

## Phase 2.6 follow-up（2026-09-13）

上述建議的parser contract與小型fixture tests已完成，見[parser-contract.md](parser-contract.md)。本節只連結後續成果，不改寫Phase 2.5的原始觀察或transition結論。
