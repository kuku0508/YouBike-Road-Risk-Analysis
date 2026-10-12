"""Read-only Phase 8.1 production completion validator."""
from __future__ import annotations
import argparse, hashlib, json, sqlite3, zlib
from pathlib import Path
import pandas as pd
from run_brouter_production import content_hash, sha256_file

EXPECTED_ROUTES=1_100_919
EXPECTED_TRIP_WEIGHT=83_693_979

def validate(root: Path):
    root=root.resolve();cfg=json.loads((root/'config/brouter_production.yaml').read_text(encoding='utf8'))
    manifest_path=root/cfg['paths']['manifest'];cache_path=root/cfg['paths']['cache_db'];progress_path=root/cfg['paths']['progress']
    manifest=pd.read_parquet(manifest_path,columns=['route_id','cache_key','trip_count'])
    if len(manifest)!=EXPECTED_ROUTES or manifest.route_id.duplicated().any():raise ValueError('manifest route count/uniqueness gate failed')
    expected={str(r.route_id):(str(r.cache_key),int(r.trip_count)) for r in manifest.itertuples(index=False)}
    counts={};trip_weight=0;fingerprint=hashlib.sha256();invalid=0
    db=sqlite3.connect(f'file:{cache_path.resolve().as_posix()}?mode=ro',uri=True)
    integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
    if integrity!='ok':raise ValueError('production cache integrity check failed')
    for route_id,cache_key,status,stored_hash,blob in db.execute('SELECT route_id,cache_key,status,content_hash,payload FROM routes ORDER BY route_id'):
        target=expected.pop(str(route_id),None)
        try:record=json.loads(zlib.decompress(blob))
        except Exception as exc:raise ValueError(f'unreadable cache payload: {route_id}') from exc
        valid=target is not None and target==(str(cache_key),int(record.get('trip_count',-1))) and status=='success' and record.get('status')=='success' and record.get('cache_key')==cache_key and stored_hash==record.get('content_hash')==content_hash(record)
        if not valid:invalid+=1
        counts[status]=counts.get(status,0)+1;trip_weight+=int(record.get('trip_count',0));fingerprint.update(f'{route_id}|{cache_key}|{status}|{stored_hash}\n'.encode())
    schema='\n'.join(r[0] for r in db.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY name"));db.close()
    progress=json.loads(progress_path.read_text(encoding='utf8'))
    identity_ok=int(progress['cache_hits'])+int(progress['actual_brouter_executions'])==EXPECTED_ROUTES
    invariants={'manifest_routes':len(manifest),'cache_rows':sum(counts.values()),'cache_status_counts':counts,'missing_manifest_routes_in_cache':len(expected),'invalid_cache_records':invalid,'successful_trip_weight':trip_weight,'failed_trip_weight':0 if set(counts)=={'success'} else None,'remaining':EXPECTED_ROUTES-counts.get('success',0),'cache_hit_execution_identity':identity_ok,'progress_matches_cache':progress['success']==counts.get('success',0) and progress['failure']==0 and progress['remaining']==0 and progress['successful_trip_weight']==trip_weight}
    if invariants!={'manifest_routes':EXPECTED_ROUTES,'cache_rows':EXPECTED_ROUTES,'cache_status_counts':{'success':EXPECTED_ROUTES},'missing_manifest_routes_in_cache':0,'invalid_cache_records':0,'successful_trip_weight':EXPECTED_TRIP_WEIGHT,'failed_trip_weight':0,'remaining':0,'cache_hit_execution_identity':True,'progress_matches_cache':True}:raise ValueError(f'production completion gate failed: {invariants}')
    return {'phase':'8.1C','validation_status':'pass','validated_read_only':True,'full_routing_rerun':False,'road_segment_aggregation_started':False,'manifest_sha256':sha256_file(manifest_path),'cache_integrity_check':integrity,'cache_schema_sha256':hashlib.sha256(schema.encode()).hexdigest(),'route_state_fingerprint_sha256':fingerprint.hexdigest(),'invariants':invariants,'progress':progress}

def main():
    root=Path(__file__).resolve().parents[1];p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=root);p.add_argument('--output',type=Path,default=root/'notes/phase8_1c-production-completion.json');a=p.parse_args();result=validate(a.root);a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8');print(json.dumps(result['invariants']))
if __name__=='__main__':main()
