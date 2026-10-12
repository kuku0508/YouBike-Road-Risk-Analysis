# Phase 4.1 — Primary OD Aggregation

## 結論

依`od-inclusion-policy-v1`完成2023/01–2025/03共27個monthly OD partitions，以及2023、2024、core 2023–2024、full 2023/01–2025/03四個aggregates。Primary OD使用`origin_station_id → destination_station_id`作為directed edge，`trip_count`為唯一edge weight；未使用duration、bike type、比例或距離加權。

大型Parquet位於Git忽略的`data/processed/od/`。可提交的逐月／aggregate receipt見[`od-aggregation-manifest.json`](od-aggregation-manifest.json)。

## 觀測邊界

**Observed dataset boundary / source mechanism**：資料來自臺北市政府YouBike票證資料，因此觀測到的旅次起點皆為臺北市站點；目的地可以延伸至新北市。

- 臺北→臺北：可觀測。
- 臺北→新北：可觀測。
- 新北→臺北：不在此來源的完整觀測範圍。
- 新北→新北：不在此來源的完整觀測範圍。

因此`New Taipei → Taipei = 0`與`New Taipei → New Taipei = 0`不可解讀為現實世界沒有這些旅次，也不是使用者行為結論。

## 固定契約

- Inclusion：只使用Phase 4.0分類為`od_eligible`的records；沒有重新判定candidate、ambiguous、unresolved、missing或quarantine。
- Node key：只使用station ID。站名與city只是display metadata。
- Edge direction：origin→destination。
- Edge weight：每筆eligible trip使`trip_count += 1`。
- Repeated records：全部計入，沒有deduplication。
- Self-loop：同站借還保留；是否在SNA排除留待Phase 4.2決策。
- Ordering：所有monthly與aggregate outputs固定按`origin_station_id, destination_station_id`排序。

## Period definitions

- **Report-specified scope / primary reconstruction scope**：core 2023/01–2024/12，共91,138,763 trips。
- **Reconstruction execution scope**：full available 2023/01–2025/03，共108,077,420 trips。
- 2025/01–03只作延伸、robustness或update，不得默默混入原報告核心network。

## Aggregate summary

| Period | Trips | OD edges | Nodes | Origins | Destinations | Self-loop trips | Self-loop edges |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2023 | 35,960,266 | 776,556 | 2,450 | 1,318 | 2,450 | 2,500,130 | 1,318 |
| 2024 | 55,178,497 | 924,021 | 2,758 | 1,503 | 2,758 | 3,523,438 | 1,501 |
| Core 2023–2024 | 91,138,763 | 1,125,519 | 2,782 | 1,506 | 2,782 | 6,023,568 | 1,504 |
| Full 2023–2025/03 | 108,077,420 | 1,211,515 | 2,865 | 1,555 | 2,865 | 7,007,723 | 1,555 |

Full-period self-loop trip proportion為6.483984%。這只是OD descriptive QA，不是network importance或行為機制推論。

## Monthly edge counts

| Month | Eligible trips | Edges | Month | Eligible trips | Edges |
|---|---:|---:|---|---:|---:|
| 2023/01 | 2,616,890 | 274,849 | 2024/03 | 3,420,558 | 334,583 |
| 2023/02 | 2,763,405 | 280,126 | 2024/04 | 3,746,878 | 350,827 |
| 2023/03 | 3,684,853 | 319,551 | 2024/05 | 4,291,775 | 363,898 |
| 2023/04 | 3,280,543 | 320,366 | 2024/06 | 3,732,658 | 334,227 |
| 2023/05 | 3,556,040 | 317,568 | 2024/07 | 5,466,388 | 364,288 |
| 2023/06 | 3,285,497 | 294,290 | 2024/08 | 6,112,587 | 386,870 |
| 2023/07 | 2,988,431 | 287,716 | 2024/09 | 5,734,604 | 372,987 |
| 2023/08 | 2,662,886 | 273,709 | 2024/10 | 5,195,425 | 379,314 |
| 2023/09 | 2,800,654 | 289,258 | 2024/11 | 5,812,579 | 408,609 |
| 2023/10 | 2,779,003 | 299,799 | 2024/12 | 6,431,844 | 421,281 |
| 2023/11 | 2,876,130 | 301,872 | 2025/01 | 5,488,956 | 407,950 |
| 2023/12 | 2,665,934 | 290,614 | 2025/02 | 5,247,440 | 398,021 |
| 2024/01 | 2,687,330 | 294,280 | 2025/03 | 6,202,261 | 435,867 |
| 2024/02 | 2,545,871 | 298,496 |  |  |  |

## City flow audit

Eligible full-period trips：

- Taipei→Taipei：106,302,441。
- Taipei→New Taipei：1,774,979。
- New Taipei→Taipei：0（來源觀測邊界，非行為零流量）。
- New Taipei→New Taipei：0（來源觀測邊界，非行為零流量）。
- Other／unresolved city：0。

## Node inventory與label consistency

`data/processed/od/node_inventory.parquet`包含2,865個station IDs、canonical display name、city、是否作為origin／destination、first/last observed month、total outgoing/incoming trips；沒有centrality欄位。

Cleaned observations中有2個station IDs曾對應多個display labels：`500108038`與`500109047`。它們分別對應既有metadata已記錄的歷史更名，不拆node、不修改identity；output deterministic label使用current official metadata優先，其次historical snapshot，最後station-universe evidence。Machine manifest保留原始observed label conflicts。

## Conservation與determinism

- 每月`sum(trip_count)`均等於Phase 4.0 monthly eligible records。
- Core aggregate為91,138,763。
- Full aggregate為108,077,420。
- Eligible 108,077,420 + excluded 1,636,479 = total input 109,713,899。
- 27 monthly + 4 aggregate + node inventory共32個output hashes在獨立重跑中完全一致。
- 第一次執行曾因PyArrow對`year=...`路徑的Hive partition inference與檔內year型別衝突而fail closed；沒有finalized partial output。改以單檔reader並新增回歸測試後成功，eligibility或policy沒有變更。

## Performance與output size

- Final wall-clock runtime：346.40秒。
- Approximate peak working set：2,243,461,120 bytes（約2.09 GiB；Windows process peak working set，於每月結束取樣）。
- Monthly OD Parquet：25,978,732 bytes（27 partitions）。
- Aggregate OD Parquet：10,554,986 bytes（4 periods）。
- Node inventory另為63,691 bytes；全部大型outputs均未commit。

## Scope boundary

本階段沒有建立graph object，也沒有計算weighted degree、centrality、PageRank、Louvain、clustering coefficient、routing或事故指標。Top OD pair即使日後列出，也只能作raw flow QA，不能稱network importance。
