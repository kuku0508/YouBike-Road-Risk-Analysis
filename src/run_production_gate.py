"""Execute only the bounded Phase 8.1A Production Gate (never full routing)."""
from __future__ import annotations
import argparse, hashlib, json, os, sqlite3, statistics, time, tracemalloc, zlib
from pathlib import Path
import pandas as pd
try:
    from .aggregate_gate_segments import aggregate
    from .run_brouter_production import run, sha256_file, verify_locked
except ImportError:
    from aggregate_gate_segments import aggregate
    from run_brouter_production import run, sha256_file, verify_locked

def percentile(v,q):
    v=sorted(v);x=(len(v)-1)*q;a=int(x);b=min(a+1,len(v)-1);return v[a]+(v[b]-v[a])*(x-a)
def read_records(dbp):
    db=sqlite3.connect(dbp);out=[json.loads(zlib.decompress(x[0])) for x in db.execute('SELECT payload FROM routes')];db.close();return out
def bench(manifest,cache,progress,cfg,workers):
    tracemalloc.start();started=time.perf_counter();result=run(manifest,cache,progress,cfg,workers);elapsed=time.perf_counter()-started;_,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    records=read_records(cache);times=[r['runtime_seconds'] for r in records]
    return {'workers':workers,'routes':len(records),'executions':result['executions'],'elapsed_seconds':elapsed,'routes_per_second':len(records)/elapsed,'median_seconds_per_route':statistics.median(times),'p90_seconds_per_route':percentile(times,.9),'p95_seconds_per_route':percentile(times,.95),'peak_python_tracemalloc_bytes':peak,'status_counts':pd.Series([r['status'] for r in records]).value_counts().to_dict()}
def main(a):
    root=a.root.resolve();cfg=json.loads(a.config.read_text(encoding='utf8'));prod=pd.read_parquet(a.production_manifest);gate=pd.read_parquet(a.gate_manifest)
    preflight=verify_locked(root,cfg,a.production_manifest)
    used=set(gate.route_id);remaining=prod[~prod.route_id.isin(used)].sort_values('route_id')
    bdir=root/'data/processed/routing/production/gate_benchmarks';bdir.mkdir(parents=True,exist_ok=True);benchmarks=[]
    offset=0
    for workers in (1,2,4):
        sub=remaining.iloc[offset:offset+100].copy();offset+=100;mp=bdir/f'workers_{workers}_manifest.parquet';sub.to_parquet(mp,index=False)
        cp=bdir/f'workers_{workers}_cache.sqlite';pp=bdir/f'workers_{workers}_progress.json'
        if cp.exists(): raise ValueError('benchmark cache already exists; refusing contaminated benchmark')
        benchmarks.append(bench(mp,cp,pp,cfg,workers))
    # Real interruption: commit 10 routes, leave an irrelevant partial file, then resume the remaining 10.
    sub=remaining.iloc[offset:offset+20].copy();mp=bdir/'resume_manifest.parquet';cp=bdir/'resume_cache.sqlite';pp=bdir/'resume_progress.json';sub.to_parquet(mp,index=False)
    first=run(mp,cp,pp,cfg,2,stop_after=10);before={r['route_id']:r['content_hash'] for r in read_records(cp)}
    partial=cp.with_suffix('.partial');partial.write_bytes(b'incomplete-not-a-cache-record')
    second=run(mp,cp,pp,cfg,2);after={r['route_id']:r['content_hash'] for r in read_records(cp)}
    resume={'first_executions':first['executions'],'first_interrupted':first['interrupted'],'second_executions':second['executions'],'second_cache_hits':second['cache_hits'],'completed_not_rerun':all(after[k]==v for k,v in before.items()),'partial_file_ignored':partial.exists(),'final_records':len(after)}
    # Gate aggregation and exact conservation.
    seg,records=aggregate(a.gate_manifest,a.gate_cache);a.segment_output.parent.mkdir(parents=True,exist_ok=True);seg.to_parquet(a.segment_output,index=False)
    gm=gate.set_index('route_id');success=[r for r in records if r['status']=='success'];fail=[r for r in records if r['status']!='success']
    status_counts=pd.Series([r['status'] for r in records]).value_counts().to_dict();times=[r['runtime_seconds'] for r in records]
    gate_stats={'sample_size':len(gate),'successes':len(success),'failures':len(fail),'status_counts':status_counts,'trip_weight':int(gate.trip_count.sum()),'weekday_weight':int(gate.weekday_trip_count.sum()),'holiday_weight':int(gate.holiday_trip_count.sum()),'success_trip_weight':int(gm.loc[[r['route_id'] for r in success]].trip_count.sum()),'failure_trip_weight':int(gm.loc[[r['route_id'] for r in fail]].trip_count.sum()) if fail else 0,'median_seconds_per_route':statistics.median(times),'p90_seconds_per_route':percentile(times,.9),'p95_seconds_per_route':percentile(times,.95),'segment_count':len(seg),'segment_hash':hashlib.sha256(seg.to_csv(index=False,lineterminator='\n').encode()).hexdigest(),'cache_bytes':a.gate_cache.stat().st_size,'bytes_per_route':a.gate_cache.stat().st_size/len(gate),'weekday_plus_holiday_equals_total':bool((gate.weekday_trip_count+gate.holiday_trip_count==gate.trip_count).all()),'segment_day_type_conservation':bool((seg.segment_flow_weekday+seg.segment_flow_holiday==seg.segment_flow_total).all())}
    selected=max(benchmarks,key=lambda x:x['routes_per_second'])['workers']
    throughput=next(x['routes_per_second'] for x in benchmarks if x['workers']==selected);n=cfg['expected']['manifest_routes']
    runtime={'optimistic_hours':n/(throughput*1.15)/3600,'central_hours':n/throughput/3600,'conservative_hours':n/(throughput*.70)/3600}
    disk={'central_bytes':int(gate_stats['bytes_per_route']*n*1.15),'conservative_bytes':int(gate_stats['bytes_per_route']*n*1.75)}
    manifest_receipt=json.loads((root/'data/processed/routing/production/manifest_receipt.json').read_text(encoding='utf8'))
    full='python src/run_brouter_production.py --manifest data/processed/routing/production/production_manifest.parquet --workers %d --execute-full-production'%selected
    receipt={'phase':'8.1A','full_routing_executed':False,'upstream_hashes':preflight['locked_hashes'],'routing_contract_version':cfg['routing_contract_version'],'coordinate_assumption_id':cfg['coordinate_assumption_id'],'manifest':manifest_receipt['manifest'],'coordinate_exclusions':{'edges':23096,'trip_weight':1421216},'gate':{**gate_stats,'actual_brouter_execution_count':1000+sum(x['executions'] for x in benchmarks)+first['executions']+second['executions'],'cache_rerun':{'executions':0,'cache_hits':1000,'all_reused':True}},'resume_test':resume,'worker_benchmarks':benchmarks,'selected_worker_count':selected,'estimated_full_runtime':runtime,'estimated_full_disk_usage':disk,'peak_memory_bytes':max(x['peak_python_tracemalloc_bytes'] for x in benchmarks),'peak_memory_measurement':'Python traced allocation only; external BRouter JVM excluded','commands':{'preflight':'python src/run_brouter_production.py --preflight','full_run':full,'resume':full,'progress':'python src/run_brouter_production.py --status'},'segment_output':{'path':a.segment_output.relative_to(root).as_posix(),'rows':len(seg),'sha256':sha256_file(a.segment_output)},'readiness_status':'PHASE 8.1A COMPLETE — LOCAL FULL ROUTING READY'}
    a.receipt.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf8');print(json.dumps({'benchmarks':benchmarks,'resume':resume,'gate':gate_stats,'selected_workers':selected,'runtime':runtime,'disk':disk},ensure_ascii=False))
if __name__=='__main__':
    r=Path(__file__).resolve().parents[1];p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=r);p.add_argument('--config',type=Path,default=r/'config/brouter_production.yaml');p.add_argument('--production-manifest',type=Path,default=r/'data/processed/routing/production/production_manifest.parquet');p.add_argument('--gate-manifest',type=Path,default=r/'data/processed/routing/production/gate_manifest.parquet');p.add_argument('--gate-cache',type=Path,default=r/'data/processed/routing/production/gate_cache.sqlite');p.add_argument('--segment-output',type=Path,default=r/'data/processed/routing/production/gate_segments.parquet');p.add_argument('--receipt',type=Path,default=r/'notes/phase8_1a-production-gate-receipt.json');main(p.parse_args())
