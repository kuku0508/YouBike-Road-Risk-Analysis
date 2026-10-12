# Phase 8.0A｜Historical coordinate evidence sources

## Sources receipt

| Source | Type / date | Authority assessment | SHA-256 / access result |
| --- | --- | --- | --- |
| Preserved Taipei official-feed capture | dated snapshot, 2024-05-31 | official endpoint content preserved by a third-party archive; usable as dated evidence, but no validity interval | `c696c0f23f55cef97862c324468781d85b752bd5f9557e3608e691f9c930634a` |
| Taipei official current endpoint | current snapshot, 2026-09-13 | official current evidence only | `0ac45607a811c3d7dde8727f2d1d4e005dcece367b1411c211eabfa2496f6969` |
| New Taipei official current endpoint | current snapshot, 2026-09-14 | official current evidence only | `325d0adc6b89ee986fd8abf1cd453d67ba645cd70432c92404436aa991578d27` |
| Taipei Open Data dataset page | current, one-minute endpoint | official metadata confirms station ID and latitude/longitude fields; no public historical resource discovered on the listing | <https://data.taipei/dataset/detail?id=c6bc8aed-557d-41d5-bfb1-8da24f78f2fb> |
| New Taipei Open Data dataset page/API | current, five-minute endpoint | official metadata confirms station ID and latitude/longitude fields; no public historical resource discovered on the listing | <https://data.gov.tw/dataset/146969> |
| TDX historical station interface | dated query documented | MOTC-supported interface can query a date, but client ID/secret is required and was unavailable in this run | <https://bookdown.org/chiajungyeh/TDX_Guide/transport-application.html> |

檢索日期：2026-09-19。外部搜尋用來發現來源；只有實際下載、hash 固定的三個本機 snapshots 進入 ledger。TDX 文件只是可重現的下一步入口，不被計為已取得 evidence。

## Source gaps

- 臺北：有 2024-05-31 單點 snapshot 與 2026 current snapshot，但缺少足以覆蓋 2023 至 2024 全期間的多時點官方檔。
- 新北：核心 1,276 nodes 全部只有 2026 current evidence；這是來源覆蓋缺口，不能解讀成站點當時沒有座標。
- 官方 current pages 的更新頻率不代表平台提供歷史版本。
- 非官方站名清單、地圖與 fuzzy geocoding 沒有進入 primary evidence。

## Reproducible next evidence request

下一個任務只能取得 TDX 或兩市交通局的 dated 2023/2024 station snapshots，至少涵蓋研究期起點、2024-05-31 前後、研究期終點；每份都必須保存 URL／查詢日期、retrieval timestamp、raw hash 與 exact station-ID mapping。沒有憑證時，應由分析者提供 TDX client credentials 或正式申請／匯出的檔案，而不是降級證據標準。

## Added in Phase 8.0B

User-provided `active_station_all.csv`（SHA-256 `8bf19851f7e9329b0f7207f84b149ce243ca9f6d1e6270ffb5f382b1a9e63205`）已加入combined ledger，但authority=`provenance_unverified_supporting_only`。Repository、Git history與exact filename web search均未找到產生程式或官方upstream URL；不得把它列為Tier 1。
