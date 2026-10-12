# Phase 8.6A-2 — Interactive CBI-guided Case Review Map

本階段把 Phase 8.6A 已固定的人工候選清冊轉成單一 Folium／Leaflet HTML，讓研究者縮放、切換平假日圖層並點擊微路段查看 canonical 指標。它不是新的風險分析、排名、hotspot detector或自動選案工具。

## Locked sources

- Phase 8.6A worksheet：1,283個唯一primary candidates；SHA-256 `660566e42801bbba51e20020985217bd3583c47188d8acaba56c48c4fa236893`。
- Phase 8.6A QA／receipt fingerprints：`cd8212fa9a3076a0d8cf4ccbc9c2d38751675fa011deb719419809a56dda0ba6`／`9a62a25cb51b222866ecd4076c5490675be9a15829121d6c9ddb854e49a03a79`。
- Phase 8.5C presentation artifact：106,057 rows；fingerprint `2e6d9f763b0370abbf3785c9e510f04b36cde415947b156eccc7223129af2ea0`；Parquet SHA-256 `8d818cd74c7b52d65488c5a0c0a97223f9ef7569e0d1ac35a26d2ca0b3e83ddc`。

所有identity在產圖前fail closed驗證。地圖幾何直接由既有EPSG:4326 canonical endpoints轉為Leaflet LineString，沒有snap、simplify、merge、buffer或corridor重建。

## Layer contract

地圖只包含下列六個可切換圖層：

- Weekday — `above_q95` primary review
- Weekday — `q90_q95` primary review
- Weekday — `q75_q90` secondary context
- Holiday — `above_q95` primary review
- Holiday — `q90_q95` primary review
- Holiday — `q75_q90` secondary context

四個primary圖層預設開啟；兩個secondary context圖層預設關閉。沒有載入`zero`、`positive_le_q50`或`q50_q75`。範圍由實際候選幾何deterministically取得並以`fit_bounds`顯示，不hard-code臺北中心。

顏色沿用Phase 8.6A：`q75_q90=#e6b75c`、`q90_q95=#3d82b8`、`above_q95=#153f67`。Primary使用相同線寬，secondary只降低線寬與opacity以維持可讀性；線寬不編碼CBI、EPDO、flow或其他metric。

Weekday／Holiday只表示該microsegment是否進入相應day type的high-flow presentation universe。CBI本身不是day-type-specific；同一段在兩個圖層出現時仍是同一個physical segment與相同CBI。

## Interaction contract

Primary popup顯示segment ID、CBI／SRI／SSI、事故件數、fatal／injury件數、EPDO、長度、平假日high-flow狀態、兩種estimated exposure與EPDO per 1,000，以及visualization class與day-type candidate狀態。Secondary popup只顯示segment ID、CBI、accident count與EPDO。Hover tooltip僅保留segment ID、CBI及primary的day-type狀態。

顯示格式只影響文字：指標原始值沒有被修改；null明確呈現`N/A`。地圖不寫回worksheet，也沒有`selected`、`context_only`或`not_selected`按鈕。研究者完成檢視後，仍需在下一個獨立步驟人工更新worksheet並留下理由。

## Basemap and portability

輸出是單一portable HTML，候選geometry與properties寫入檔案；Folium產生的Leaflet／plugin assets及OpenStreetMap底圖皆使用remote resources，因此實際開啟地圖時需要網路。工具沒有reverse geocoding、Google Maps API、ROADNAME推定或任何依道路名稱自動選案的邏輯。

## Determinism and limits

Folium可能產生不同DOM element IDs，因此不要求整份HTML byte-level SHA在不同執行間相同。正式可重現識別是`map_data_fingerprint`，其輸入包含segment ID、day-type layer membership、canonical metrics、geometry、style class及display contract，不包含DOM IDs或產生時間。

候選單位仍是BRouter physical microsegment，不是官方道路corridor。Display classes只協助人工檢視，不是風險分類、hotspot或排名。A3／PDO-only unavailable、BRouter exposure為estimated、事故matching exclusions與10 m analytical threshold持續存在；本階段沒有街景判讀、道路改善建議、corridor aggregation或Phase 8.6B。

## Validation

- Phase 8.6A-2 focused tests：28／28 passed。
- Full regression suite：582／582 passed。
- 真實artifact的primary／secondary unique counts、weekday／holiday membership、popup canonical values、geometry endpoints、style contract及HTML layer bindings均通過。
- 兩次正式重建的`map_data_fingerprint`一致；Folium DOM IDs與執行時間不納入此指紋。
- 自動化瀏覽器因安全政策禁止開啟本機`file://` URL，故沒有聲稱完成live browser visual QA。研究者首次使用時仍應在本機瀏覽器人工確認remote tiles、layer toggles、zoom、hover與popup互動。

Readiness：**PHASE 8.6A-2 COMPLETE — INTERACTIVE HUMAN REVIEW MAP READY**。最終案例仍須由研究者人工選擇並提供明確理由。

## 呈現層繁體中文化與可操作性

互動地圖的圖層名稱、圖例、popup、tooltip、地圖說明與控制項文字已改為台灣繁體中文；內部欄位、canonical values、candidate membership 與 `map_data_fingerprint` 的資料語意不變。`True / False` 顯示為「是／否」，`weekday / holiday` 顯示為「平日／假日」，候選狀態顯示為「僅平日／僅假日／平日與假日」。

正式線寬固定為：`q90_q95=5.5 px`、`above_q95=5.5 px`、`q75_q90=3.0 px`；hover 時分別暫時變為 `7.5 px`、`7.5 px`、`5.0 px`，mouseout 後恢復。兩個 primary class 使用完全相同線寬，線寬不依 CBI、EPDO、事故數、exposure 或其他分析指標動態計算。

「視覺化級距僅用於縮小人工檢視範圍，不代表熱點定義或危險程度排名。」
