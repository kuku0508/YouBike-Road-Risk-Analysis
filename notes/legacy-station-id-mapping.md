# Phase 8.0B｜Legacy station identity mapping

## Method

只使用 deterministic evidence，依序為：

1. legacy name exact match 2024-05-31 historical metadata中的唯一 station ID；
2. exact match core monthly OD／既有 cleaning pipeline中已唯一對應的 raw trip name；
3. exact match既有 versioned approved allowlist alias。

所有來源的 deterministic candidate ID union 必須唯一。0 IDs為unmatched；多於1 ID為ambiguous。Current-only metadata只可 supporting，不能自行建立historical identity。沒有使用 Levenshtein、substring、embedding、nearest coordinate、道路名稱、strip `_1`／`_2`、入口編號或方向詞。

## Mapping results

| Mapping status | Legacy names | Unique canonical IDs | Endpoint-involved non-self OD edges | Endpoint-involved trip weight | Acceptance |
| --- | ---: | ---: | ---: | ---: | --- |
| Exact historical-name candidate | 1,411 | 1,411 | 1,119,064 | 85,076,835 | Identity accepted; coordinates supporting-only |
| Exact trip-name candidate | 1,358 | 1,358 | 242,976 | 2,787,062 | Identity accepted; coordinates supporting-only |
| Known-alias candidate | 0 | 0 | 0 | 0 | None needed |
| Ambiguous | 0 | 0 | 0 | 0 | Fail closed |
| Unmatched | 246 | — | Not attributable | Not attributable | Unresolved |

Individual status impacts可重疊，不能相加成union coverage。兩端同屬historical-name set的edges／trips為876,472／82,006,519；兩端同屬trip-name set為4,312／33,960。這些只是identity impact，不是可routing coverage，因provenance gate尚未通過。

共2,769個canonical IDs取得唯一 deterministic mapping：Taipei 1,502、New Taipei 1,267。沒有 canonical ID 收到多個 legacy names，也沒有 mapping collision。結果很好，但不能彌補來源不可追溯。

## Anomalies and collisions

246個 unmatched raw names保存在 `legacy_station_name_anomalies.parquet`，含原字串、Base64、first／last month、months observed、valid-coordinate row count、candidate IDs與 unresolved status。未執行 fuzzy candidate generation，因此candidate IDs為空；未重新掃描raw trips估算其trip frequency。

缺座標不做forward fill、backward fill或interpolation。`_1`／`_2`與入口／方向標記均原樣保留。
