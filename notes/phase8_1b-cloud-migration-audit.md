# Phase 8.1B-M｜Cloud migration bundle audit

## Scope and live-production boundary

本階段只盤點、快照、封裝與clean-room驗證。Production runner、Java/BRouter service、worker count、live SQLite DB/WAL/SHM及progress均未被停止或修改；沒有啟動第二個full runner、Google Cloud VM、upload或cloud benchmark。

## Runtime dependency graph

```text
run_brouter_production.py
├─ config/brouter_production.yaml
│  ├─ production_manifest.parquet                 [execution]
│  ├─ routing_station_coordinates_2023_2024.parquet [preflight/audit]
│  ├─ core_2023_2024/od.parquet                   [preflight]
│  ├─ routing_contract.yaml                       [preflight/audit]
│  └─ routing_coordinate_assumption.yaml          [preflight/audit]
├─ route_segment_utils.py                         [execution import]
├─ audit_routing_contract.py                      [execution import: haversine]
├─ BRouter 1.7.10 JAR + trekking.brf + 2 RD5     [execution/preflight]
├─ route_cache.sqlite                             [resume]
└─ progress.json                                  [status/audit; reconstructible]
```

Manifest builder、hourly OD buckets、raw monthly YouBike檔、notebooks、plots、Phase 3–7 artifacts、Git objects與unrelated HTML不屬於Phase 8.1B runtime bundle。Production manifest已固定，不需在VM重建。

## SQLite safety

Live DB：`data/processed/routing/production/route_cache.sqlite`；WAL與SHM存在，journal mode為WAL。直接copy DB/WAL/SHM不被接受。Bundle builder只用SQLite Online Backup API，來源以`mode=ro`開啟，輸出到獨立staging DB，再執行`PRAGMA integrity_check`與status counts。Live WAL/SHM不進bundle。

Online backup是SQLite支援的consistent snapshot機制；它不要求停止writer，但snapshot只代表backup完成時點。若未來最終搬移時需要零新增差異，仍應controlled stop後再做一次final online backup。

## Linux compatibility

Production runner使用`pathlib`、標準`java`命令、Python SQLite與HTTP loopback；沒有hard-coded `C:\`、`java.exe`、PowerShell-only subprocess或Windows encoding依賴。新增Linux shell launcher只使用bundle-relative paths並bind `127.0.0.1:17777`。沒有修改cache identity、routing contract或分析語意。

已知status caveat：同一次resume invocation的display throughput以completed/elapsed計算，可能把cache hits納入分子，造成ETA過度樂觀。真正new-routing throughput應看`actual_brouter_executions / elapsed_seconds`。本階段只文件化，未擴大修改runner。

## Evidence boundary

Phase 8.0B的`LEGACY HISTORICAL COORDINATES: NOT SUFFICIENTLY TRACEABLE`與Phase 8.0C analyst assumption均原樣打包；migration不提升其證據等級。

## M2 corrective record：real cloud deployment defects

原Phase 8.1B-M bundle audit在本機clean room通過，但後續於Google Cloud實際啟動時暴露三項缺陷；因此不得把原始結果改寫成一開始就完整正確：

1. Bundle漏帶`profiles2/lookups.dat`，雖然RouteServer port可連線，每次route仍因`FileNotFoundException`失敗。
2. Bundle只帶hash固定的dated RD5，Linux runtime沒有BRouter查找的`E120_N20.rd5`／`E120_N25.rd5` canonical filenames，造成`datafile ... not found`。
3. 舊preflight只測TCP socket，無法辨認「process alive但route execution broken」。

M2將`lookups.dat`固定為explicit runtime dependency（SHA-256 `bf8fc3b2c052b7204e9c5a8d78e4d6ab6b125d3236a943f34583b838c477f419`）；dated RD5內容與hash維持不變，由Linux launcher建立並驗證relative symlinks，不複製graph payload。`--preflight`另以Phase 8.1A gate已成功的route `00087cf1126a2a927ebb1931`（約3.38 km直線距離）發出真實HTTP request、使用production GeoJSON parser，並要求success、有效segments與route hash。Smoke test不開cache、不寫progress、weight為0，也不算production route。

HTTP 4xx/5xx現在保存status、reason與最多4,096 bytes的UTF-8 replacement-decoded body；這只改善diagnostics，不改failure taxonomy。

## Observed Google Cloud benchmark（environment-specific）

Google Cloud Compute Engine `asia-east1`、`e2-standard-2` Spot、Debian 13、2 vCPU／8 GB RAM、Java 25.0.4.1、Python 3.11.16、pandas 3.0.3、pyarrow 21.0.0；修復runtime依賴後：

| Workers | Routes | Success | Failure | Cache hits | Executions | Elapsed (s) | routes/s |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1,000 | 1,000 | 0 | 0 | 1,000 | 212.5851287841797 | 4.70399790295406 |
| 2 | 1,000 | 1,000 | 0 | 0 | 1,000 | 162.0057873725891 | 6.1726189923088945 |

本機Phase 8.1A參考為1 worker約8.075 routes/s、4 workers約9.128 routes/s。這些都是特定環境與sample的實測，不代表cloud VM普遍較慢。因本次`e2-standard-2`的validated throughput實質低於既有i5-12500，本次不選它承接full production；沒有啟動full cloud production，本機production保持authoritative。
