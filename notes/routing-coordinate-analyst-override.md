# Phase 8.0C｜Routing coordinate analyst override

## Preserved evidence conclusion

Phase 8.0B 的結論仍是 **LEGACY HISTORICAL COORDINATES: NOT SUFFICIENTLY TRACEABLE**。`active_station_all.csv`的官方upstream無法驗證，且所有mapped station跨月座標過度穩定，存在事後static lookup回填的合理疑慮。這次沒有撤回、改寫或把來源升為Tier 1。

## Explicit reconstruction assumption

Decision `D110`／assumption `routing-coordinate-assumption-v1`：只為完成本次重建，將`active_station_all.csv`各月份exact-mapped record所附coordinate視為該站該月可用的routing coordinate。

Machine-readable contract將兩個概念分開：

- `evidence_status = supporting_unverified_provenance`
- `routing_acceptance = accepted_by_analyst_assumption`

來源hash與mapping hash皆為fail-closed gate。Identity仍只接受Phase 8.0B既有exact evidence；沒有fuzzy、substring、nearest-coordinate或suffix stripping。

## Scope and reversibility

Month只具`YYYY-MM`精度。若未來取得verified historical metadata，保留raw legacy file與本decision，產生新版coordinate artifact，逐站比較差異，使coordinate hash受影響的route cache失效，再重跑受影響OD；不能覆寫舊假設使其看似從未存在。
