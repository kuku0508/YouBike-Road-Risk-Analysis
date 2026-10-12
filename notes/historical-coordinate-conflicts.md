# Phase 8.0A｜2024/2026 coordinate conflicts

31 個 conflict 全部維持 `unresolved_conflict`。兩個 snapshots 無法指出變更發生日期；即使只有 4.51 m，也不能單靠距離宣告 precision difference。站名變化只作 supporting context，未裁決座標。

| Station ID | Geodesic displacement (m) | QA bin | Resolution |
| --- | ---: | --- | --- |
| 500104057 | 207.544 | ≥100m | unresolved_conflict |
| 500111028 | 155.377 | ≥100m | unresolved_conflict |
| 500109065 | 155.221 | ≥100m | unresolved_conflict |
| 500107016 | 154.988 | ≥100m | unresolved_conflict |
| 500104076 | 120.330 | ≥100m | unresolved_conflict |
| 500108022 | 117.329 | ≥100m | unresolved_conflict |
| 500107133 | 110.785 | ≥100m | unresolved_conflict |
| 500105025 | 109.687 | ≥100m | unresolved_conflict |
| 500104107 | 97.046 | 30–100m | unresolved_conflict |
| 500107008 | 86.534 | 30–100m | unresolved_conflict |
| 500109068 | 84.738 | 30–100m | unresolved_conflict |
| 500101015 | 80.124 | 30–100m | unresolved_conflict |
| 500104075 | 71.049 | 30–100m | unresolved_conflict |
| 500109047 | 67.670 | 30–100m | unresolved_conflict |
| 500107075 | 61.893 | 30–100m | unresolved_conflict |
| 500108132 | 59.190 | 30–100m | unresolved_conflict |
| 500104032 | 55.078 | 30–100m | unresolved_conflict |
| 500101199 | 54.815 | 30–100m | unresolved_conflict |
| 500119084 | 51.308 | 30–100m | unresolved_conflict |
| 500112017 | 45.215 | 30–100m | unresolved_conflict |
| 500108013 | 44.968 | 30–100m | unresolved_conflict |
| 500101166 | 42.449 | 30–100m | unresolved_conflict |
| 500110027 | 39.851 | 30–100m | unresolved_conflict |
| 500113037 | 38.346 | 30–100m | unresolved_conflict |
| 500101159 | 37.622 | 30–100m | unresolved_conflict |
| 500107033 | 33.601 | 30–100m | unresolved_conflict |
| 500105009 | 33.598 | 30–100m | unresolved_conflict |
| 500112089 | 30.616 | 30–100m | unresolved_conflict |
| 500101180 | 20.926 | 15–30m | unresolved_conflict |
| 500108006 | 11.827 | 5–15m | unresolved_conflict |
| 500113012 | 4.514 | <5m | unresolved_conflict |

Distribution：p50 59.190 m、p90 154.988 m、p95 155.299 m、max 207.544 m；8 站 ≥100 m、20 站 30–100 m、其餘三個 bins 各 1 站。分類結果為 precision difference 0、after-period relocation 0、within-period relocation 0、unresolved 31；前三者是「未能建立」，不是反證其不存在。

## Phase 8.0B legacy timeline

31/31可由exact identity接回；8個legacy coordinates等於2024位置、20個等於2026位置、3個兩者皆非。所有legacy station timelines本身都固定為單一座標。因provenance未確認，31個仍是`unresolved_conflict`；尤其20個較新的座標被列在2023–2024 months，阻止將`month`解釋為coordinate snapshot date。
