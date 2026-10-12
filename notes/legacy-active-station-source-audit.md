# Phase 8.0B｜`active_station_all.csv` source audit

## Conclusion

**Provenance result：unverified。** 這份檔案可作 supporting candidate evidence，但不能宣告為官方 monthly station metadata，也不能單獨提升為 Tier 1。

Repository working tree、全部 Git history／objects、README、notes、R／Python scripts、notebooks及精確檔名網路搜尋均未找到 `active_station_all`、產生程式、原始 URL 或 commit lineage。檔案是使用者於 2026-09-19 提供的本機 raw file；原始 bytes 未修改。

## Raw source receipt

| Item | Observed |
| --- | --- |
| Path | `data/raw/active_station_all.csv` |
| Size | 7,322,758 bytes |
| SHA-256 | `8bf19851f7e9329b0f7207f84b149ce243ca9f6d1e6270ffb5f382b1a9e63205` |
| Rows | 64,413 data rows |
| Columns | 7，含 R `write.csv` 風格的空白 row-name 欄 |
| Encoding | UTF-8 為主；strict decode 失敗 |
| Illegal bytes | 106 bytes、5種 byte values |
| Affected station fields / records | 75 / 75 |
| Parsing | strict UTF-8 gate → UTF-8 `surrogateescape` lossless parse；每個名稱欄另存 exact Base64 |
| Width errors | 0 |

不得用 `errors="replace"`。可顯示文字中的非法 bytes 以 `\xNN` escape 表示；identity comparison 使用原始 bytes／Base64，不會把 replacement character 當原值。

## Schema and value audit

欄位為：空白 row-name、`month`、`站點`、`站點編號`、`站點標籤`、`經度`、`緯度`。

`站點編號` 並非 canonical station ID：全檔沒有任何值符合 `500\d{6}`。62,790 rows 的 `站點編號` 與 `站點` 完全相同；core period 的54,913個有效座標 rows中，`站點`、`站點編號`與`站點標籤`三欄全部相同。其餘缺座標 rows 的後三個 metadata欄多為 `NA`。因此禁止 `legacy 站點編號 == canonical station_id` join。

## Month semantics

`month` 完整涵蓋 `youbike_202301` 至 `youbike_202503`；core 24 months 每個 month-name 組合唯一。Repository 沒有 extraction code，因此只能確認它是月份級 observation/group label，不能判定為月初、月底或某日 snapshot，也不能虛構日級 valid interval。

### Reconstruction inference—not observed provenance

下列共同現象比較符合「monthly active／trip-observed name list 後續接上一份靜態座標 lookup」，而不是逐月保存官方 metadata：

- 每月每個 station name 恰有一列；rows 隨月份由2,131增至2,641。
- 2,769個成功 identity-mapped IDs 在所有月份都只有一組 exact coordinate。
- 31個既有 2024／2026 conflict IDs中，legacy coordinate有20個等於2026位置、8個等於2024位置、3個兩者皆非，而且這些位置被回填到更早月份。

這只是根據資料形狀的推論，不是已確認的產生流程；它正是不能把 CSV 當 historical snapshot authority 的理由。

## Sources receipt

- 使用者提供本機 raw CSV：已保存 path、size、hash、encoding與retrieval status。
- Repository／Git history：無 filename、field lineage或source URL命中。
- Web exact-filename search：無公開結果。
- Phase 8.0A 既有官方／保存 snapshots：只用於 exact identity與coordinate comparison，未反向改寫 raw CSV。
