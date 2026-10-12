"""Resume-safe, bounded-memory BRouter production runner.

The full manifest is executable only with ``--execute-full-production``.
Preflight/status/gate modes can never trigger the full universe.
"""
from __future__ import annotations
import argparse, concurrent.futures, hashlib, json, math, os, shutil, socket, sqlite3, statistics, subprocess, sys, time, urllib.error, urllib.parse, urllib.request, zlib
from pathlib import Path
from types import SimpleNamespace
import pandas as pd
import pyarrow.parquet as pq
try:
    from .route_segment_utils import parse_geojson_route
    from .audit_routing_contract import haversine
except ImportError:
    from route_segment_utils import parse_geojson_route
    from audit_routing_contract import haversine

TERMINAL={"success","no_route","malformed_output","snap_anomaly"}; RETRYABLE={"timeout","brouter_error"}
KNOWN_STATES=TERMINAL|RETRYABLE
HTTP_ERROR_BODY_LIMIT=4096
def sha256_file(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf8");os.replace(tmp,path)
def content_hash(record):
    keep={k:v for k,v in record.items() if k not in {"content_hash","cache_hit"}}
    return hashlib.sha256(json.dumps(keep,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
def validate_record(r,expected):
    if r["cache_key"]!=expected or r["status"] not in TERMINAL: return False
    return r.get("content_hash")==content_hash(r)
def db_open(path):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);db=sqlite3.connect(p);db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS routes(route_id TEXT PRIMARY KEY, cache_key TEXT NOT NULL, status TEXT NOT NULL, content_hash TEXT NOT NULL, payload BLOB NOT NULL, updated_at REAL NOT NULL)");db.commit();return db
def cache_get_current(db,route_id,expected):
    row=db.execute("SELECT payload FROM routes WHERE route_id=?",(route_id,)).fetchone()
    if not row:return None
    try:
        r=json.loads(zlib.decompress(row[0]))
        if r.get("cache_key")!=expected or r.get("status") not in KNOWN_STATES:return None
        return r if r.get("content_hash")==content_hash(r) else None
    except Exception:return None
def cache_get(db,route_id,expected):
    r=cache_get_current(db,route_id,expected)
    return r if r is not None and r["status"] in TERMINAL else None
def cache_put_many(db,records):
    now=time.time();rows=[]
    for r in records:
        r=dict(r);r["content_hash"]=content_hash(r);raw=zlib.compress(json.dumps(r,separators=(",",":"),ensure_ascii=False).encode(),6)
        rows.append((r["route_id"],r["cache_key"],r["status"],r["content_hash"],raw,now))
    with db: db.executemany("INSERT OR REPLACE INTO routes VALUES(?,?,?,?,?,?)",rows)
def refresh_record_weights(record,row):
    updated=dict(record)
    for key in ("trip_count","weekday_trip_count","holiday_trip_count"):
        updated[key]=int(getattr(row,key))
    for key in ("origin_city","destination_city","approx_distance_m","origin_coordinate_conflict","destination_coordinate_conflict"):
        value=getattr(row,key);updated[key]=bool(value) if key.endswith("coordinate_conflict") else (float(value) if key=="approx_distance_m" else value)
    updated["content_hash"]=content_hash(updated);return updated
def request_route(row,cfg):
    env=cfg["environment"]; params=dict(env["routing_parameters"]);params["lonlats"]=f"{row.origin_lon},{row.origin_lat}|{row.destination_lon},{row.destination_lat}"
    url=env["base_url"]+"?"+urllib.parse.urlencode(params,safe="|,"); started=time.perf_counter(); attempts=0;last=None
    for attempts in range(1,cfg["execution"]["max_attempts"]+1):
        try:
            with urllib.request.urlopen(url,timeout=cfg["execution"]["request_timeout_seconds"]) as response: raw=response.read()
            try:
                parsed=parse_geojson_route(json.loads(raw));coords=parsed["coordinates"]
                offsets=(haversine((row.origin_lon,row.origin_lat),tuple(coords[0][:2])),haversine((row.destination_lon,row.destination_lat),tuple(coords[-1][:2])))
                threshold=cfg["execution"]["snap_anomaly_threshold_m"]
                status="snap_anomaly" if threshold is not None and max(offsets)>threshold else "success"
                props=parsed["properties"];dist=props.get("track-length",props.get("distance"))
                record={"route_id":row.route_id,"origin_station_id":row.origin_station_id,"destination_station_id":row.destination_station_id,"trip_count":int(row.trip_count),"weekday_trip_count":int(row.weekday_trip_count),"holiday_trip_count":int(row.holiday_trip_count),"origin_city":row.origin_city,"destination_city":row.destination_city,"approx_distance_m":float(row.approx_distance_m),"origin_coordinate_conflict":bool(row.origin_coordinate_conflict),"destination_coordinate_conflict":bool(row.destination_coordinate_conflict),"cache_key":row.cache_key,"status":status,"attempts":attempts,"runtime_seconds":time.perf_counter()-started,"route_distance_m":float(dist),"origin_snap_offset_m":offsets[0],"destination_snap_offset_m":offsets[1],"segment_count":parsed["segment_count"],"segments":parsed["segments"],"route_hash":parsed["route_hash"],"output_hash":hashlib.sha256(raw).hexdigest(),"environment":{"pipeline":cfg["pipeline_version"],"contract":cfg["routing_contract_version"],"brouter":env["brouter_version"],"profile_hash":cfg["locked_hashes"]["profile"],"graph_hashes":cfg["locked_hashes"]["graphs"]}}
                record["content_hash"]=content_hash(record);return record
            except Exception as exc:
                last={"status":"malformed_output","error":repr(exc)};break
        except urllib.error.HTTPError as exc:
            body=exc.read(HTTP_ERROR_BODY_LIMIT+1);truncated=len(body)>HTTP_ERROR_BODY_LIMIT;body=body[:HTTP_ERROR_BODY_LIMIT]
            detail=body.decode("utf8",errors="replace")
            last={"status":"brouter_error","error":f"HTTPError {exc.code} {exc.reason}: {detail}","http_status":exc.code,"http_reason":str(exc.reason),"http_response_body":detail,"http_response_body_truncated":truncated}
        except TimeoutError as exc:last={"status":"timeout","error":repr(exc)}
        except Exception as exc:last={"status":"brouter_error","error":repr(exc)}
        if attempts<cfg["execution"]["max_attempts"]:time.sleep(.1*attempts)
    r={"route_id":row.route_id,"origin_station_id":row.origin_station_id,"destination_station_id":row.destination_station_id,"trip_count":int(row.trip_count),"weekday_trip_count":int(row.weekday_trip_count),"holiday_trip_count":int(row.holiday_trip_count),"origin_city":row.origin_city,"destination_city":row.destination_city,"approx_distance_m":float(row.approx_distance_m),"origin_coordinate_conflict":bool(row.origin_coordinate_conflict),"destination_coordinate_conflict":bool(row.destination_coordinate_conflict),"cache_key":row.cache_key,"status":last["status"],"attempts":attempts,"runtime_seconds":time.perf_counter()-started,"error":last.get("error"),"environment":{"pipeline":cfg["pipeline_version"]}}
    for key in ("http_status","http_reason","http_response_body","http_response_body_truncated"):
        if key in last:r[key]=last[key]
    r["content_hash"]=content_hash(r);return r
def smoke_test_route(cfg):
    smoke=cfg["environment"]["preflight_smoke_route"]
    row=SimpleNamespace(**smoke,trip_count=0,weekday_trip_count=0,holiday_trip_count=0,origin_city="preflight",destination_city="preflight",approx_distance_m=0.0,origin_coordinate_conflict=False,destination_coordinate_conflict=False,cache_key="preflight-no-cache")
    record=request_route(row,cfg)
    if record["status"]!="success":raise ValueError(f"BRouter real-route preflight failed: {record.get('error',record['status'])}")
    return {"route_id":record["route_id"],"source":smoke["source"],"status":record["status"],"route_distance_m":record["route_distance_m"],"segment_count":record["segment_count"],"route_hash":record["route_hash"],"cache_written":False,"progress_written":False}
def verify_locked(root,cfg,manifest=None,perform_route_smoke=True):
    h=cfg["locked_hashes"];paths=cfg["paths"];checks={"od":sha256_file(root/paths["od"]),"coordinates":sha256_file(root/paths["coordinates"]),"brouter_jar":sha256_file(root/cfg["environment"]["jar"]),"profile":sha256_file(root/cfg["environment"]["profile"]),"lookups":sha256_file(root/cfg["environment"]["lookups"])}
    for k,v in checks.items():
        if v!=h[k]:raise ValueError(f"locked hash mismatch: {k}")
    if [sha256_file(root/p) for p in cfg["environment"]["graphs"]]!=h["graphs"]:raise ValueError("locked graph hash mismatch")
    contract=json.loads((root/"config/routing_contract.yaml").read_text(encoding="utf8"));assumption=json.loads((root/"config/routing_coordinate_assumption.yaml").read_text(encoding="utf8"))
    if contract["contract_version"]!=cfg["routing_contract_version"] or assumption["assumption_id"]!=cfg["coordinate_assumption_id"]:raise ValueError("contract/assumption gate failed")
    java=subprocess.run(["java","-version"],capture_output=True,text=True).stderr
    if cfg["environment"]["java_version_prefix"] not in java:raise ValueError("Java version gate failed")
    free=shutil.disk_usage(root).free
    if free<cfg["execution"]["minimum_free_disk_bytes"]:raise ValueError("insufficient disk space")
    parsed=urllib.parse.urlparse(cfg["environment"]["base_url"])
    try:
        with socket.create_connection((parsed.hostname,parsed.port),timeout=2): pass
    except OSError as exc: raise ValueError("locked local BRouter service unavailable") from exc
    smoke=smoke_test_route(cfg) if perform_route_smoke else None
    return {"locked_hashes":checks,"java":java.splitlines()[0],"free_disk_bytes":free,"brouter_service":f"{parsed.hostname}:{parsed.port} reachable","real_route_smoke_test":smoke,"manifest":str(manifest) if manifest else None}
def manifest_row_count(path): return pq.ParquetFile(path).metadata.num_rows
def manifest_batches(path,batch_size,max_routes=None):
    emitted=0
    for batch in pq.ParquetFile(path).iter_batches(batch_size=batch_size):
        frame=batch.to_pandas()
        if max_routes is not None: frame=frame.head(max_routes-emitted)
        if len(frame): yield frame
        emitted+=len(frame)
        if max_routes is not None and emitted>=max_routes: break
def initial_cache_counters(db):
    counts={};sw=fw=0
    for cache_key,blob in db.execute("SELECT cache_key,payload FROM routes"):
        try:
            record=json.loads(zlib.decompress(blob))
            if record.get('cache_key')!=cache_key or record.get('status') not in KNOWN_STATES or record.get('content_hash')!=content_hash(record):continue
            status=record['status'];w=int(record.get('trip_count',0))
        except Exception:continue
        counts[status]=counts.get(status,0)+1
        if status=='success':sw+=w
        else:fw+=w
    return counts,sw,fw
def apply_state_transition(counts,success_weight,failure_weight,old_record,new_record):
    if old_record is not None:
        old_status=old_record['status'];old_weight=int(old_record.get('trip_count',0))
        counts[old_status]=counts.get(old_status,0)-1
        if counts[old_status]<0:raise ValueError(f'negative route-state count: {old_status}')
        if counts[old_status]==0:counts.pop(old_status)
        if old_status=='success':success_weight-=old_weight
        else:failure_weight-=old_weight
    new_status=new_record['status'];new_weight=int(new_record.get('trip_count',0))
    counts[new_status]=counts.get(new_status,0)+1
    if new_status=='success':success_weight+=new_weight
    else:failure_weight+=new_weight
    if success_weight<0 or failure_weight<0:raise ValueError('negative route-state trip weight')
    return success_weight,failure_weight
def progress_snapshot(total,counts,sw,fw,started):
    done=sum(counts.values());elapsed=max(.001,time.time()-started);rate=done/elapsed
    return {"total_routes":total,"completed":done,"success":counts.get("success",0),"failure":done-counts.get("success",0),"remaining":total-done,"elapsed_seconds":elapsed,"throughput_routes_per_second":rate,"estimated_remaining_seconds":(total-done)/rate if rate else None,"successful_trip_weight":sw,"failed_trip_weight":fw}
def run(manifest_path,cache_path,progress_path,cfg,workers,max_routes=None,stop_after=None):
    total=min(manifest_row_count(manifest_path),max_routes) if max_routes else manifest_row_count(manifest_path);db=db_open(cache_path);started=time.time();cache_hits=0;executions=0;results=[];counts,success_weight,failure_weight=initial_cache_counters(db)
    try:
        for batch in manifest_batches(manifest_path,cfg["execution"]["batch_size"],max_routes):
            todo=[];refreshed=[];prior_by_route={};cached_pairs=[]
            for r in batch.itertuples(index=False):
                current=cache_get_current(db,r.route_id,r.cache_key)
                if current is not None and current['status'] in TERMINAL:
                    cache_hits+=1;updated=refresh_record_weights(current,r);refreshed.append(updated);cached_pairs.append((current,updated))
                else:
                    todo.append(r)
                    if current is not None:prior_by_route[r.route_id]=current
            if stop_after is not None: todo=todo[:max(0,stop_after-executions)]
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:new=list(pool.map(lambda r:request_route(r,cfg),todo))
            cache_put_many(db,refreshed+new);results.extend(new);executions+=len(new)
            for old,updated in cached_pairs:
                success_weight,failure_weight=apply_state_transition(counts,success_weight,failure_weight,old,updated)
            for r in new:
                success_weight,failure_weight=apply_state_transition(counts,success_weight,failure_weight,prior_by_route.get(r['route_id']),r)
            prog=progress_snapshot(total,counts,success_weight,failure_weight,started);prog.update({"cache_hits":cache_hits,"actual_brouter_executions":executions,"last_flush_utc":time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())});atomic_json(progress_path,prog)
            if stop_after is not None and executions>=stop_after:break
    except KeyboardInterrupt:
        atomic_json(progress_path,{**progress_snapshot(total,counts,success_weight,failure_weight,started),"cache_hits":cache_hits,"actual_brouter_executions":executions,"interrupted":True});return {"interrupted":True,"executions":executions,"cache_hits":cache_hits}
    finally:db.close()
    return {"interrupted":bool(stop_after is not None and executions>=stop_after),"executions":executions,"cache_hits":cache_hits,"new_result_count":len(results),"progress":json.loads(Path(progress_path).read_text(encoding="utf8"))}
def status(cache,manifest,progress):
    m=pd.read_parquet(manifest);p=json.loads(Path(progress).read_text(encoding="utf8")) if Path(progress).exists() else {};counts={}
    if Path(cache).exists():
        db=sqlite3.connect(f"file:{Path(cache).resolve().as_posix()}?mode=ro",uri=True);counts=dict(db.execute("SELECT status,COUNT(*) FROM routes GROUP BY status").fetchall());db.close()
    return {"manifest_routes":len(m),"cache_status_counts":counts,**p}
def main(a):
    root=a.root.resolve();cfg=json.loads(a.config.read_text(encoding="utf8"));manifest=a.manifest or root/cfg["paths"]["manifest"];cache=a.cache or root/cfg["paths"]["cache_db"];progress=a.progress or root/cfg["paths"]["progress"]
    if a.status: print(json.dumps(status(cache,manifest,progress),ensure_ascii=False,indent=2));return
    print(json.dumps(verify_locked(root,cfg,manifest),ensure_ascii=False))
    if a.preflight:return
    mrows=manifest_row_count(manifest)
    if mrows==cfg["expected"]["manifest_routes"] and not a.execute_full_production:raise SystemExit("Refusing full manifest without --execute-full-production")
    out=run(manifest,cache,progress,cfg,a.workers,a.max_routes,a.stop_after);print(json.dumps(out,ensure_ascii=False,default=str))
if __name__=="__main__":
    r=Path(__file__).resolve().parents[1];p=argparse.ArgumentParser();p.add_argument("--root",type=Path,default=r);p.add_argument("--config",type=Path,default=r/"config/brouter_production.yaml");p.add_argument("--manifest",type=Path);p.add_argument("--cache",type=Path);p.add_argument("--progress",type=Path);p.add_argument("--workers",type=int,default=4);p.add_argument("--max-routes",type=int);p.add_argument("--stop-after",type=int);p.add_argument("--preflight",action="store_true");p.add_argument("--status",action="store_true");p.add_argument("--execute-full-production",action="store_true");main(p.parse_args())
