# Phase 8.1C｜BRouter production completion

## Scope and evidence labels

- **Report-specified**：原報告以BRouter Trekking為OD建立模擬道路路徑並將旅次權重累加至共同路段；原報告沒有保存本次production cache、resume或runtime incident數字。
- **Reconstruction decision**：`road-routing-contract-v1.1`、固定BRouter／profile／RD5／coordinates與1,100,919-route manifest沿用Phase 8.1A；SQLite中通過content-hash與cache-key驗證的current route state是完成狀態的authority。
- **Runtime observation**：本頁的完成數字、service interruption、Windows Update與resume行為來自本次production artifacts與已檢查的system events。
- **Assumption**：Phase 8.0C coordinate analyst assumption維持不變；production完成不會把legacy coordinates提升為verified historical facts。

本階段只做final validation、retry accounting修正與文件收尾；沒有重跑full routing，也沒有開始Phase 8.2 road-segment aggregation。

## Final artifact validation

唯讀validator逐筆核對manifest與SQLite compressed payload，而非只讀progress摘要：

| Invariant | Result |
|---|---:|
| Manifest routes | 1,100,919 |
| Cache rows／unique route IDs | 1,100,919／1,100,919 |
| Cache status | success 1,100,919 |
| Missing manifest routes | 0 |
| Invalid cache key／content hash／weight records | 0 |
| Successful trip weight | 83,693,979 |
| Failed trip weight | 0 |
| Remaining | 0 |
| SQLite integrity check | ok |

`348,100 cache hits + 752,819 actual BRouter executions = 1,100,919 manifest routes`；progress與authoritative cache一致。Manifest SHA-256仍為`9d9691a81ffa5f804224ee270890cf5acf579db8d53342574229d503290834ee`；final route-state fingerprint為`1a69cd69be3983779d20abc64667936561526d156f363d64bcf7cd49c31d7b37`。Machine-readable receipt見[`phase8_1c-production-completion.json`](phase8_1c-production-completion.json)。

## Runtime incidents and resume evidence

1. 較早一次production中，BRouter service停止監聽；cache當時有222,654 success與1,646 `brouter_error`，近期錯誤為connection refused。只能確認service stopped listening，不能宣稱其精確原因。Runner將`brouter_error`視為retryable；以Ctrl+C乾淨停止並flush state。
2. Service重啟後，real-route preflight以`datafile E120_N25.rd5 not found` fail closed。Dated RD5存在，但Windows runtime canonical filenames缺失。Windows以NTFS hard links建立`E120_N20.rd5`／`E120_N25.rd5`，兩組canonical與dated檔SHA-256相同；大檔與hard links均不進Git。Linux migration launcher則以validated relative symlinks處理。
3. Restart後preflight通過，1,646個retryable records全數重算成功；cache曾到224,400 success且不再含`brouter_error`。
4. 同一次resume曾觀察到top-level failure仍保留1,646，雖cache current states已轉為success。這是display/accounting defect，不是final route failure；乾淨process restart後摘要重新一致。
5. 2026-09-20的Windows System events顯示06:59與07:01為MoUsoCoreWorker／TrustedInstaller觸發的planned OS restart（Event ID 1074），並有正常Event Log shutdown（6006）；檢查中沒有Kernel-Power 41或6008異常關機證據。重啟前約348,100 successes，重啟後全數以cache hits復原並續跑，構成真實resume-safety evidence。

## Retry accounting defect and fix

舊runner啟動時以cache current rows初始化status counts；retryable row因不是terminal cache hit而會重新routing。成功結果寫回時，舊程式只增加`success`，沒有減去同route先前的`brouter_error`及failed trip weight，因此一個route暫時同時存在於兩組top-level counters。

修正後先讀取並驗證每個route的current cached state，再以原子資料庫寫入後的`old state → new state` transition更新counts與trip weights。Retry成功會先扣除舊failure，再加入success；terminal cache hit的weight refresh也使用同一transition helper。Initial counters只接受cache key、known status與content hash皆有效的payload。Routing、retry、WAL、Ctrl+C、preflight與cache semantics均未改變。

## Completion

**PHASE 8.1 ROUTING PRODUCTION: COMPLETE**

Phase 8.2尚未開始。下一階段若獲明確授權，才可進行road-segment aggregation；該聚合仍須保留self-loop與coordinate-gap exclusions、BRouter failure accounting及Phase 8.0C provenance caveat。
