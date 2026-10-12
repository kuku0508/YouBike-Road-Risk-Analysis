# Phase 8.1A｜Production Routing Pipeline & Gate

## Status

**PHASE 8.1A COMPLETE — LOCAL FULL ROUTING READY**

本階段建立production manifest、streaming runner、SQLite transactional cache、atomic progress checkpoint、resume、bounded gate與segment validation。實際BRouter executions為1,320（1,000 gate＋300隔離benchmark＋20 interruption/resume），低於5,000上限；沒有啟動1,100,919-route full run。

## Locked inputs

OD、final coordinate、BRouter JAR、Trekking profile與兩個RD5 hashes全部吻合。Contract為`road-routing-contract-v1.1`，coordinate assumption為`routing-coordinate-assumption-v1`。Phase 8.0B的`NOT SUFFICIENTLY TRACEABLE`結論未修改。

Production manifest為1,100,919 directed non-self routes、83,693,979 trips。Day-type weights由Phase 7.3的48個`IsHoliday` authoritative hourly OD buckets聚合：weekday 61,065,093、holiday 22,628,886，逐OD及全域皆滿足weekday＋holiday＝total。23,096 coordinate-gap OD／1,421,216 trips只列為pre-routing exclusions，不混入BRouter failure denominator。

## Gate result

- Deterministic representative sample：1,000 routes，含flow/distance strata、Taipei→Taipei、Taipei→New Taipei、reciprocal pairs與coordinate-conflict endpoints。
- Success：1,000；failure：0；sample trip weight 67,816。
- Cache rerun：1,000 hits、0 BRouter executions。
- Interruption/resume：10 routes完成後停止；restart只執行剩餘10，已完成10條content hashes不變；irrelevant partial file未被當成cache record。
- Gate segments：48,989 directed segment keys；segment hash `208fea2bab29adf42ec303d53e112544ee400160bc119f3ca24664408c3c30e8`。
- OD status與trip-weight守恆、每segment weekday＋holiday＝total全部通過。`Σsegment_flow`不拿來對等`Σtrips`。

Cache採單一SQLite WAL資料庫，避免百萬散落GeoJSON；每個payload以zlib壓縮、保留per-route cache key／content hash／terminal status。Writes以validated batch transaction atomic commit；progress以temporary file＋atomic replace。Runner以Parquet record batches串流manifest，不把1.1M geometry或segment sequences一次載入RAM。

Gate sample實際含741條Taipei→Taipei、259條Taipei→New Taipei、43條涉及coordinate-conflict endpoint及2條reciprocal routes；trip count範圍1–7,518、approximate distance範圍179–22,779m。

Validation：37/37 production-specific tests與316/316完整regression tests通過。

## Sources receipt

- `data/processed/od/aggregate/core_2023_2024/od.parquet`：OD universe與weights。
- `data/processed/routing/routing_station_coordinates_2023_2024.parquet`：固定routing endpoints。
- `data/processed/network/hourly_2023_2024/day_type=*/hour=*/od.parquet`：Phase 7.3 `IsHoliday`權重。
- `config/routing_contract.yaml`、`config/routing_coordinate_assumption.yaml`、`config/brouter_production.yaml`：契約與locked identities。

以上均由本機hash gate與receipt固定；本階段沒有外部引擎fallback。
