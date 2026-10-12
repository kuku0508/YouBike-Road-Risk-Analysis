# Phase 8.1B-M｜Google Cloud VM migration runbook

## Local packaging

```powershell
python src/build_cloud_migration_bundle.py
```

如果是最終移交，先依[`phase8_1b-final-cache-snapshot-procedure.md`](phase8_1b-final-cache-snapshot-procedure.md)controlled stop並重建bundle。驗證archive：

```powershell
Get-FileHash data/interim/youbike_phase8_1b_cloud_bundle.tar.gz -Algorithm SHA256
```

## Upload template（本階段不要執行）

```powershell
gcloud compute scp data/interim/youbike_phase8_1b_cloud_bundle.tar.gz data/interim/youbike_phase8_1b_cloud_bundle.tar.gz.sha256 VM_NAME:~/ --zone=ZONE --project=PROJECT_ID
```

## Cloud extraction and verification

```bash
sha256sum -c youbike_phase8_1b_cloud_bundle.tar.gz.sha256
mkdir -p ~/youbike_phase8_1b
tar -xzf youbike_phase8_1b_cloud_bundle.tar.gz -C ~/youbike_phase8_1b
cd ~/youbike_phase8_1b
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r environment/cloud-runtime-requirements.txt
chmod +x scripts/start_brouter_linux.sh
sha256sum data/raw/routing/brouter-v1.7.10/brouter-1.7.10/profiles2/lookups.dat
scripts/start_brouter_linux.sh > brouter.log 2>&1 &
# launcher會fail closed並建立／驗證：
readlink data/raw/routing/E120_N20.rd5
readlink data/raw/routing/E120_N25.rd5
python src/run_brouter_production.py --preflight
python src/run_brouter_production.py --status
```

`lookups.dat`預期SHA-256為`bf8fc3b2c052b7204e9c5a8d78e4d6ab6b125d3236a943f34583b838c477f419`。Launcher只在canonical path不存在時建立relative symlink；既有symlink target不符或既有non-symlink都會拒絕覆寫。`--preflight`不只是socket probe，還必須完成一條既有gate route並通過production GeoJSON parser。禁止從「port reachable」直接跳到benchmark或full production。

## Cloud benchmark（已完成的bounded evidence）

實際`e2-standard-2` Spot benchmark以未cached 1,000 routes測得1 worker 4.704、2 workers 6.173 routes/s，皆1,000/1,000成功。此VM未被選為full production環境；不得用cache hits灌高throughput，也不得直接從bounded benchmark進full run。

## Full production command（只供後續核准）

```bash
python src/run_brouter_production.py --manifest data/processed/routing/production/production_manifest.parquet --workers 1 --execute-full-production
```

Resume使用相同command。雲端worker數必須等VM benchmark後決定；runbook先用1 worker保守啟動，不沿用本機4 workers假設。

## Download back

1. 按一次`Ctrl+C`並等待flush。
2. 用SQLite Online Backup API建立consistent cache snapshot；不要直接copy live DB/WAL/SHM。
3. 將snapshot、status metadata打包並計算SHA-256。
4. 使用`gcloud compute scp VM_NAME:~/OUTPUT_ARCHIVE . --zone=ZONE --project=PROJECT_ID`下載。
5. 本機先驗hash與`PRAGMA integrity_check`，再考慮resume。
