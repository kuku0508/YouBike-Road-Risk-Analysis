"""Create a deterministic, Linux-friendly Phase 8.1B migration bundle.

The live cache is read only through SQLite's online backup API.  This script
never stops, signals, restarts, or writes to the production runner/cache.
"""
from __future__ import annotations
import argparse, gzip, hashlib, json, os, shutil, sqlite3, subprocess, sys, tarfile, tempfile, time
from pathlib import Path

PIPELINE_VERSION="phase8.1b-migration-bundle-v2"
LOOKUPS_SHA256="bf8fc3b2c052b7204e9c5a8d78e4d6ab6b125d3236a943f34583b838c477f419"
def sha256_file(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()
def copy_file(src,dst):
    dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
def validate_lookups(root,cfg):
    path=root/cfg['environment']['lookups']
    if not path.is_file():raise FileNotFoundError(f'missing BRouter runtime dependency: {path}')
    digest=sha256_file(path)
    if digest!=LOOKUPS_SHA256 or digest!=cfg['locked_hashes']['lookups']:raise ValueError('lookups.dat locked hash mismatch')
    return digest
def sqlite_snapshot(source,destination):
    destination.parent.mkdir(parents=True,exist_ok=True)
    uri=f"file:{source.resolve().as_posix()}?mode=ro"
    with sqlite3.connect(uri,uri=True,timeout=30) as src, sqlite3.connect(destination) as dst:
        mode=src.execute('PRAGMA journal_mode').fetchone()[0]
        src.backup(dst,pages=256,sleep=.01)
    with sqlite3.connect(destination) as db:
        integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
        counts=dict(db.execute('SELECT status,COUNT(*) FROM routes GROUP BY status').fetchall())
        schema='\n'.join(r[0] for r in db.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY name"))
        # A backup inherits WAL mode from the source.  Convert the independent
        # snapshot to a single-file journal before packaging; never bundle
        # transient snapshot sidecars (and never touch the live sidecars).
        db.execute('PRAGMA journal_mode=DELETE').fetchone()
    if integrity!='ok': destination.unlink(missing_ok=True);raise ValueError('cache snapshot integrity check failed')
    for suffix in ('-wal','-shm'):
        sidecar=Path(str(destination)+suffix)
        if sidecar.exists():
            sidecar.unlink()
    return {'method':'Python sqlite3 online backup API from read-only source connection','source_journal_mode':mode,'integrity_check':integrity,'status_counts':counts,'rows':sum(counts.values()),'schema_sha256':hashlib.sha256(schema.encode()).hexdigest()}
def deterministic_tar_gz(source,archive):
    archive.parent.mkdir(parents=True,exist_ok=True)
    with archive.open('wb') as raw, gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0,compresslevel=6) as gz, tarfile.open(fileobj=gz,mode='w') as tar:
        for p in sorted(source.rglob('*'),key=lambda x:x.relative_to(source).as_posix()):
            rel=p.relative_to(source).as_posix();info=tar.gettarinfo(str(p),arcname=rel);info.uid=info.gid=0;info.uname=info.gname='';info.mtime=0
            if p.is_file():
                with p.open('rb') as f:tar.addfile(info,f)
            else:tar.addfile(info)
def payload_spec():
    return [
      ('src/run_brouter_production.py','source_execution','execution'),('src/route_segment_utils.py','source_execution','execution'),('src/audit_routing_contract.py','source_execution','execution'),
      ('config/brouter_production.yaml','configuration','execution'),('config/routing_contract.yaml','contract','preflight,reproducibility'),('config/routing_coordinate_assumption.yaml','contract','preflight,reproducibility'),
      ('data/processed/routing/production/production_manifest.parquet','production_input','execution'),('data/processed/routing/routing_station_coordinates_2023_2024.parquet','production_input','preflight,reproducibility'),('data/processed/od/aggregate/core_2023_2024/od.parquet','production_input','preflight'),
      ('data/raw/routing/brouter-v1.7.10/brouter-1.7.10/brouter-1.7.10-all.jar','brouter_environment','execution'),('data/raw/routing/brouter-v1.7.10/brouter-1.7.10/profiles2/trekking.brf','brouter_environment','execution'),('data/raw/routing/brouter-v1.7.10/brouter-1.7.10/profiles2/lookups.dat','brouter_profile_runtime_dependency','execution,preflight'),('data/raw/routing/E120_N20_20260918.rd5','brouter_environment','execution'),('data/raw/routing/E120_N25_20260918.rd5','brouter_environment','execution'),
      ('notes/phase8_1a-production-gate-receipt.json','provenance','audit'),('notes/routing-coordinate-finalization-receipt.json','provenance','audit'),('notes/phase8_1b-cloud-migration-audit.md','provenance','audit'),('notes/phase8_1b-cloud-migration-runbook.md','runbook','execution,resume'),('notes/phase8_1b-final-cache-snapshot-procedure.md','runbook','resume'),
      ('environment/cloud-runtime-requirements.txt','environment','execution'),('scripts/start_brouter_linux.sh','environment','execution')]
def build(args):
    root=args.root.resolve();stage=args.stage.resolve();archive=args.archive.resolve()
    cfg=json.loads((root/'config/brouter_production.yaml').read_text(encoding='utf8'))
    validate_lookups(root,cfg)
    if root not in stage.parents: raise ValueError('staging must be inside project root')
    if stage.exists():shutil.rmtree(stage)
    stage.mkdir(parents=True)
    items=[]
    for rel,category,required in payload_spec():
        src=root/rel
        if not src.is_file():raise FileNotFoundError(src)
        dst=stage/rel;copy_file(src,dst)
        items.append({'relative_path':rel,'category':category,'required_for':required.split(','),'size_bytes':src.stat().st_size,'sha256':sha256_file(src),'source_location':rel,'bundle_destination_path':rel})
    live=root/'data/processed/routing/production/route_cache.sqlite';snap_rel='data/processed/routing/production/route_cache.sqlite';snap=stage/snap_rel
    snapshot=sqlite_snapshot(live,snap)
    items.append({'relative_path':snap_rel,'category':'resume_state_snapshot','required_for':['resume'],'size_bytes':snap.stat().st_size,'sha256':sha256_file(snap),'source_location':live.relative_to(root).as_posix(),'bundle_destination_path':snap_rel})
    status={'snapshot_created_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),**snapshot};status_rel='data/processed/routing/production/cache_snapshot_status.json';(stage/status_rel).write_text(json.dumps(status,indent=2)+'\n',encoding='utf8')
    items.append({'relative_path':status_rel,'category':'resume_state_metadata','required_for':['resume','audit'],'size_bytes':(stage/status_rel).stat().st_size,'sha256':sha256_file(stage/status_rel),'source_location':'generated_from_cache_snapshot','bundle_destination_path':status_rel})
    progress=root/'data/processed/routing/production/progress.json'
    if progress.exists():
        rel='data/processed/routing/production/progress_at_packaging.json';copy_file(progress,stage/rel);items.append({'relative_path':rel,'category':'resume_state_metadata','required_for':['audit'],'size_bytes':(stage/rel).stat().st_size,'sha256':sha256_file(stage/rel),'source_location':progress.relative_to(root).as_posix(),'bundle_destination_path':rel})
    items.sort(key=lambda x:x['relative_path'])
    manifest={'pipeline_version':PIPELINE_VERSION,'created_utc':status['snapshot_created_utc'],'routing_contract_version':cfg['routing_contract_version'],'coordinate_assumption_version':cfg['coordinate_assumption_id'],'python_version':sys.version.split()[0],'java_version':subprocess.run(['java','-version'],capture_output=True,text=True).stderr.splitlines()[0],'brouter_version':cfg['environment']['brouter_version'],'locked_hashes':cfg['locked_hashes'],'production_manifest_sha256':sha256_file(root/cfg['paths']['manifest']),'coordinate_artifact_sha256':sha256_file(root/cfg['paths']['coordinates']),'rd5_runtime_aliases':cfg['environment']['graph_runtime_aliases'],'rd5_alias_note':'aliases are reconstructed by the Linux launcher and are not independent graph payloads','cache_snapshot':status,'items':items,'excluded':['raw monthly YouBike ZIP/CSV','unrelated notebooks/plots/reports','Git objects','unrelated HTML','unrelated caches','live SQLite WAL/SHM'],'manifest_self_note':'migration_manifest.json is excluded from its own item hashes to avoid self-reference'}
    raw=json.dumps(manifest,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode();manifest['payload_fingerprint_sha256']=hashlib.sha256(raw).hexdigest()
    for p in (stage/'migration_manifest.json',stage/'notes/cloud_migration_manifest.json'):
        p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    repository_manifest=root/'notes/cloud_migration_manifest.json'
    repository_manifest.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    deterministic_tar_gz(stage,archive);digest=sha256_file(archive);archive.with_suffix(archive.suffix+'.sha256').write_text(f'{digest}  {archive.name}\n',encoding='ascii')
    return manifest,{'archive':str(archive),'size_bytes':archive.stat().st_size,'sha256':digest,'file_count':sum(p.is_file() for p in stage.rglob('*'))}
def main():
    root=Path(__file__).resolve().parents[1];p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=root);p.add_argument('--stage',type=Path,default=root/'data/interim/cloud_migration_bundle');p.add_argument('--archive',type=Path,default=root/'data/interim/youbike_phase8_1b_cloud_bundle.tar.gz');p.add_argument('--receipt',type=Path,default=root/'notes/cloud_migration_bundle_receipt.json');a=p.parse_args();m,b=build(a);a.receipt.write_text(json.dumps({'bundle':b,'payload_fingerprint_sha256':m['payload_fingerprint_sha256'],'cache_snapshot':m['cache_snapshot'],'m2_hardening':{'lookups_sha256':m['locked_hashes']['lookups'],'rd5_runtime_aliases':m['rd5_runtime_aliases'],'real_route_preflight_required':True},'cloud_benchmark':{'environment':'Google Cloud Compute Engine e2-standard-2 Spot, Debian 13','workers_1_routes_per_second':4.70399790295406,'workers_2_routes_per_second':6.1726189923088945,'full_cloud_production_started':False},'full_routing_launched':False,'cloud_resources_created':False,'upload_performed':False},indent=2)+'\n',encoding='utf8');print(json.dumps(b))
if __name__=='__main__':main()
