# Phase 7.3｜Holiday calendar audit

## Source and schema

指定且唯一的calendar來源為Git忽略的`data/raw/2020_2025假日.fst`，原檔未修改、未commit。

| Item | Observed |
| --- | --- |
| SHA-256 | `a10889e9a656d9f9c06975f0e1adb36b3b6d93955365bd91fc49308a2dd37bc5` |
| Bytes | 11,880 |
| Rows | 2,192 |
| Columns | `Date`, `IsHoliday`, `NaturalDisaster` |
| Date range | 2020-01-01–2025-12-31 |
| Representation | `Date`為R `Date`；其餘兩欄為numeric 0/1 |

檔案使用本機R 4.5.2與`fst`套件唯讀解析；Python pipeline呼叫[`export_fst_calendar.R`](../src/export_fst_calendar.R)輸出暫存CSV後立即刪除。暫存資料不是替代calendar source，所有執行仍以原FST hash為gate。

## Core-period validation

2023-01-01–2024-12-31共731天：2023為365天、2024為366天。`Date`唯一、無缺日；`IsHoliday`無null或未知值。

| Day classification | Dates |
| --- | ---: |
| `IsHoliday == 1`（holiday） | 233 |
| `IsHoliday == 0`（weekday） | 498 |
| `NaturalDisaster == 1` | 6 |

`NaturalDisaster`只保留作provenance／QA，沒有覆寫`IsHoliday`。沒有使用Python weekday、週末heuristic或自行建立的假日表。

Machine-readable版本見[`holiday-calendar-audit.json`](holiday-calendar-audit.json)。
