# Phase 8.0C｜Final routing coordinate coverage

## Coverage

| Measure | Routable / accepted | Denominator | Coverage |
|---|---:|---:|---:|
| Core nodes | 2,756 | 2,782 | 99.0654% |
| Non-self directed OD edges | 1,100,919 | 1,124,015 | 97.9452% |
| Non-self trip weight | 83,693,979 | 85,115,195 | 98.3302% |

26個gap nodes中，13個已有exact legacy identity但所有legacy coordinate皆缺失；13個沒有accepted exact mapping。按city為Taipei 17、New Taipei 9。Unroutable flow為23,096 edges／1,421,216 trips；其中origin missing 12,149 edges／705,941 trips、destination missing 10,838／707,001、兩端皆missing 109／8,274。

影響旅次最多的gap IDs依endpoint involvement為：`500110036` 326,477、`500101153` 208,665、`500101095` 118,723、`500107133` 115,744、`500107057` 105,535。Endpoint involvement會在同一OD兩端皆缺時重疊，不能相加當成unroutable union。

## Interpretation and readiness

Self-loop政策不變：1,504 edges／6,023,568 trips不送BRouter，仍納入守恆。Taipei→New Taipei OD保留；資料仍不代表完整New Taipei-origin YouBike母體。

剩餘1.6698% non-self trip weight並未被證明無系統性偏誤，因此Phase 8.1必須同時報告routed與unroutable denominators，不可把未路由流量當0或靜默drop。所有gap已逐站、逐OD、逐trip weight保存；沒有未處理coordinate-era問題。

**ROUTING COORDINATES FINALIZED — PHASE 8.1 READY WITH DISCLOSED EXCLUSIONS**

本階段沒有執行BRouter full routing。
