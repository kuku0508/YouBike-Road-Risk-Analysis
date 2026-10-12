# Phase 8.1A｜Local production runbook

## 1. BRouter service

先確認Phase 8.0已啟動且hash固定的本機BRouter v1.7.10 service，位置為`127.0.0.1:17777`。Preflight只接受locked JAR、profile、RD5與Java 25.0.4.1，不會自行更新任何檔案。

## 2. Preflight（不會routing）

```powershell
python src/run_brouter_production.py --preflight
```

這會驗證locked hashes、contract／assumption、Java、BRouter port、manifest與至少8 GiB free disk。

## 3. Full local run

```powershell
python src/run_brouter_production.py --manifest data/processed/routing/production/production_manifest.parquet --workers 4 --execute-full-production
```

`--execute-full-production`是必要的explicit gate；沒有它，full manifest會fail closed。這個command不需要Codex session存在。

## 4. Safe stop and resume

正常停止請按一次`Ctrl+C`。Runner會讓current HTTP calls回到batch boundary，將已驗證records以SQLite transaction commit，再原子寫progress；不要把`kill -9`當正常停止方式。看到command回到prompt後，可用status command確認最後flush。

Resume只需重跑同一條full command。Valid terminal cache records會skip；corrupt、stale或缺失records不算完成；retryable failure最多三次。Weights更新不會使geometry cache失效，但會刷新route-level weight欄位。

## 5. Read-only progress

```powershell
python src/run_brouter_production.py --status
```

Status mode以read-only SQLite連線查看completed、remaining、success、failure、elapsed、throughput與ETA；cache不存在時也不會建立檔案。

## 6. Boundaries

不要變更manifest、coordinate artifact、BRouter、profile、RD5或contract後沿用舊cache。Cache key會使這些變更失效。BRouter failure不使用straight line、OSRM、Google Maps或其他fallback。Phase 8.1B只執行routing；full validation與road-segment aggregation留給Phase 8.1C。
