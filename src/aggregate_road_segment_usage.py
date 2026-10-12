"""Phase 8.2 deterministic directed road-segment usage aggregation."""
from __future__ import annotations
import argparse, hashlib, json, os, sqlite3, time, zlib
from collections import Counter
from decimal import Decimal
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
try:
    from .route_segment_utils import canonical_point
    from .run_brouter_production import content_hash, sha256_file
except ImportError:
    from route_segment_utils import canonical_point
    from run_brouter_production import content_hash, sha256_file

CONTRACT_VERSION="directed-segment-usage-v1"
INT32_MIN=-(2**31);INT32_MAX=2**31-1
OUTPUT_COLUMNS=['from_lon_e6','from_lat_e6','to_lon_e6','to_lat_e6','segment_traversal_count','unique_route_count','total_trip_weight','weekday_trip_weight','holiday_trip_weight']

def coordinate_to_e6(value):
    result=int(Decimal(str(value))*1_000_000)
    if not INT32_MIN<=result<=INT32_MAX:raise ValueError('microdegree coordinate exceeds int32')
    return result

def canonicalize_and_collapse(coordinates):
    if not isinstance(coordinates,list) or len(coordinates)<2:raise ValueError('route requires at least two coordinates')
    points=[]
    for raw in coordinates:
        lon,lat=canonical_point(raw);point=(coordinate_to_e6(lon),coordinate_to_e6(lat))
        if not points or point!=points[-1]:points.append(point)
    collapsed=len(coordinates)-len(points)
    if len(points)<2:raise ValueError('success route has fewer than two distinct canonical points')
    return points,{'raw_point_count':len(coordinates),'canonical_point_count':len(points),'collapsed_consecutive_duplicate_points':collapsed,'prevented_zero_length_segments':collapsed}

def segmentize_coordinates(coordinates):
    points,qa=canonicalize_and_collapse(coordinates)
    return [(a[0],a[1],b[0],b[1]) for a,b in zip(points,points[1:])],qa

def parse_segment_key(value):
    try:left,right=value.split('->');a=left.split(',');b=right.split(',');segment=(coordinate_to_e6(a[0]),coordinate_to_e6(a[1]),coordinate_to_e6(b[0]),coordinate_to_e6(b[1]))
    except Exception as exc:raise ValueError(f'malformed canonical segment: {value!r}') from exc
    if segment[:2]==segment[2:]:raise ValueError('zero-length canonical segment')
    return segment

def validate_weights(total,weekday,holiday):
    values=(int(total),int(weekday),int(holiday))
    if any(v<0 for v in values):raise ValueError('trip weights must be nonnegative')
    if values[0]!=values[1]+values[2]:raise ValueError('weekday + holiday must equal total')
    return values

def route_contributions(segments,total,weekday,holiday):
    total,weekday,holiday=validate_weights(total,weekday,holiday);counts=Counter(segments)
    return {segment:(multiplicity,1,total*multiplicity,weekday*multiplicity,holiday*multiplicity) for segment,multiplicity in counts.items()}

def synthetic_aggregate(routes,chunk_size):
    if chunk_size<=0:raise ValueError('chunk_size must be positive')
    output={};qa=Counter()
    for start in range(0,len(routes),chunk_size):
        for route in routes[start:start+chunk_size]:
            segments,route_qa=segmentize_coordinates(route['coordinates']);qa.update(route_qa)
            for key,values in route_contributions(segments,route['total'],route['weekday'],route['holiday']).items():
                old=output.get(key,(0,0,0,0,0));output[key]=tuple(a+b for a,b in zip(old,values))
    rows=[(*key,*output[key]) for key in sorted(output)]
    fingerprint=hashlib.sha256(''.join('|'.join(map(str,row))+'\n' for row in rows).encode()).hexdigest()
    return rows,dict(qa),fingerprint

def open_work_db(path,input_identity,chunk_size):
    path.parent.mkdir(parents=True,exist_ok=True);db=sqlite3.connect(path);db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA synchronous=FULL')
    db.execute('CREATE TABLE IF NOT EXISTS usage(from_lon_e6 INTEGER,from_lat_e6 INTEGER,to_lon_e6 INTEGER,to_lat_e6 INTEGER,segment_traversal_count INTEGER,unique_route_count INTEGER,total_trip_weight INTEGER,weekday_trip_weight INTEGER,holiday_trip_weight INTEGER,PRIMARY KEY(from_lon_e6,from_lat_e6,to_lon_e6,to_lat_e6))')
    db.execute('CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY CHECK(id=1),input_identity TEXT,chunk_size INTEGER,last_route_id TEXT,processed_routes INTEGER,counters_json TEXT)')
    row=db.execute('SELECT input_identity,chunk_size FROM state WHERE id=1').fetchone()
    if row is None:db.execute('INSERT INTO state VALUES(1,?,?,NULL,0,?)',(input_identity,chunk_size,json.dumps({})));db.commit()
    elif row!=(input_identity,chunk_size):raise ValueError('stale aggregation checkpoint identity')
    return db

UPSERT='''INSERT INTO usage VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(from_lon_e6,from_lat_e6,to_lon_e6,to_lat_e6) DO UPDATE SET segment_traversal_count=segment_traversal_count+excluded.segment_traversal_count,unique_route_count=unique_route_count+excluded.unique_route_count,total_trip_weight=total_trip_weight+excluded.total_trip_weight,weekday_trip_weight=weekday_trip_weight+excluded.weekday_trip_weight,holiday_trip_weight=holiday_trip_weight+excluded.holiday_trip_weight'''

def aggregate(root,chunk_size,work_db,output):
    receipt=json.loads((root/'notes/phase8_1c-production-completion.json').read_text(encoding='utf8'));inv=receipt['invariants']
    if receipt['validation_status']!='pass' or receipt['route_state_fingerprint_sha256']!='1a69cd69be3983779d20abc64667936561526d156f363d64bcf7cd49c31d7b37' or inv['cache_status_counts']!={'success':1_100_919} or inv['successful_trip_weight']!=83_693_979:raise ValueError('Phase 8.1C completion gate failed')
    cfg=json.loads((root/'config/brouter_production.yaml').read_text(encoding='utf8'));cache=root/cfg['paths']['cache_db'];identity=receipt['route_state_fingerprint_sha256']
    source=sqlite3.connect(f'file:{cache.resolve().as_posix()}?mode=ro',uri=True);work=open_work_db(work_db,identity,chunk_size)
    last,processed,counters_raw=work.execute('SELECT last_route_id,processed_routes,counters_json FROM state WHERE id=1').fetchone();counters=Counter(json.loads(counters_raw));started=time.time()
    query='SELECT route_id,cache_key,status,content_hash,payload FROM routes '+('WHERE route_id>? ' if last else '')+'ORDER BY route_id';cursor=source.execute(query,(last,) if last else ())
    while True:
        batch=cursor.fetchmany(chunk_size)
        if not batch:break
        updates=Counter()
        for route_id,cache_key,status,stored_hash,blob in batch:
            record=json.loads(zlib.decompress(blob))
            if status!='success' or record.get('status')!='success' or record.get('route_id')!=route_id or record.get('cache_key')!=cache_key or stored_hash!=record.get('content_hash') or stored_hash!=content_hash(record):raise ValueError(f'invalid authoritative cache record: {route_id}')
            raw_segments=record.get('segments');declared=int(record.get('segment_count',-1))
            if not isinstance(raw_segments,list) or declared!=len(raw_segments) or declared<1:raise ValueError(f'invalid stored segments: {route_id}')
            segments=[parse_segment_key(x) for x in raw_segments];total,weekday,holiday=validate_weights(record['trip_count'],record['weekday_trip_count'],record['holiday_trip_count'])
            for key,values in route_contributions(segments,total,weekday,holiday).items():updates[key]=tuple(a+b for a,b in zip(updates.get(key,(0,0,0,0,0)),values))
            counters.update({'input_routes':1,'raw_points':declared+1,'canonical_points':declared+1,'effective_segment_occurrences':declared,'distinct_route_segments':len(set(segments)),'total_weighted_traversals':total*declared,'weekday_weighted_traversals':weekday*declared,'holiday_weighted_traversals':holiday*declared})
        with work:
            work.executemany(UPSERT,[(*key,*values) for key,values in updates.items()]);processed+=len(batch);last=batch[-1][0];work.execute('UPDATE state SET last_route_id=?,processed_routes=?,counters_json=? WHERE id=1',(last,processed,json.dumps(dict(counters),sort_keys=True)))
    source.close()
    if processed!=1_100_919 or counters['input_routes']!=1_100_919:raise ValueError('route-count conservation failed')
    row=work.execute('SELECT COUNT(*),SUM(segment_traversal_count),SUM(unique_route_count),SUM(total_trip_weight),SUM(weekday_trip_weight),SUM(holiday_trip_weight),SUM(CASE WHEN total_trip_weight=weekday_trip_weight+holiday_trip_weight THEN 0 ELSE 1 END) FROM usage').fetchone()
    unique_segments,traversals,unique_route_sum,total_sum,weekday_sum,holiday_sum,day_errors=map(int,row)
    expected=(counters['effective_segment_occurrences'],counters['distinct_route_segments'],counters['total_weighted_traversals'],counters['weekday_weighted_traversals'],counters['holiday_weighted_traversals'],0)
    if (traversals,unique_route_sum,total_sum,weekday_sum,holiday_sum,day_errors)!=expected:raise ValueError('segment traversal conservation failed')
    schema=pa.schema([(name,pa.int32() if name.endswith('_e6') else pa.int64()) for name in OUTPUT_COLUMNS]);tmp=output.with_suffix(output.suffix+'.tmp');output.parent.mkdir(parents=True,exist_ok=True);fingerprint=hashlib.sha256();writer=pq.ParquetWriter(tmp,schema,compression='zstd')
    out_cursor=work.execute('SELECT '+','.join(OUTPUT_COLUMNS)+' FROM usage ORDER BY from_lon_e6,from_lat_e6,to_lon_e6,to_lat_e6')
    written=0
    while True:
        rows=out_cursor.fetchmany(100_000)
        if not rows:break
        for r in rows:fingerprint.update(('|'.join(map(str,r))+'\n').encode())
        arrays=[pa.array([r[i] for r in rows],type=schema.field(i).type) for i in range(len(OUTPUT_COLUMNS))];writer.write_table(pa.Table.from_arrays(arrays,schema=schema));written+=len(rows)
    writer.close();os.replace(tmp,output);work.close()
    return {'contract_version':CONTRACT_VERSION,'completion_timestamp_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'backend':'SQLite on-disk UPSERT + PyArrow streaming Parquet export','chunk_size':chunk_size,'routing_cache_read_only':True,'brouter_called':False,'phase8_3_started':False,'input_route_count':processed,'input_route_state_fingerprint':identity,'output_unique_directed_segment_count':unique_segments,'output_row_count':written,'raw_coordinate_point_count_derived':counters['raw_points'],'canonical_coordinate_point_count_derived':counters['canonical_points'],'collapsed_consecutive_duplicate_points':0,'prevented_zero_length_segments':0,'effective_segment_occurrence_count':traversals,'sum_unique_route_count':unique_route_sum,'total_weighted_traversal_sum':total_sum,'weekday_weighted_traversal_sum':weekday_sum,'holiday_weighted_traversal_sum':holiday_sum,'conservation':{'route_count':True,'segment_traversals':True,'unique_route_counts':True,'total_weighted_traversals':True,'weekday_weighted_traversals':True,'holiday_weighted_traversals':True,'per_segment_day_type':True},'output_fingerprint_sha256':fingerprint.hexdigest(),'output_sha256':sha256_file(output),'runtime_seconds':time.time()-started}

def main():
    root=Path(__file__).resolve().parents[1];p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=root);p.add_argument('--chunk-size',type=int,default=1000);p.add_argument('--work-db',type=Path,default=root/'data/interim/routing/segment_usage_aggregation.sqlite');p.add_argument('--output',type=Path,default=root/'data/processed/routing/directed_segment_usage_2023_2024.parquet');p.add_argument('--receipt',type=Path,default=root/'notes/phase8_2-segment-usage-completion.json');a=p.parse_args();result=aggregate(a.root.resolve(),a.chunk_size,a.work_db.resolve(),a.output.resolve());a.receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8');print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
