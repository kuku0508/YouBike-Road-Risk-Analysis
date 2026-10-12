from __future__ import annotations
import argparse, json, sqlite3, zlib
from collections import defaultdict
from pathlib import Path
import pandas as pd
def aggregate(manifest,cache):
    m=pd.read_parquet(manifest).set_index('route_id');db=sqlite3.connect(cache);flows=defaultdict(lambda:[0,0,0,0])
    records=[]
    for rid,blob in db.execute("SELECT route_id,payload FROM routes"):
        r=json.loads(zlib.decompress(blob));records.append(r)
        if r['status']!='success':continue
        w=m.loc[rid]
        for s in r['segments']:
            f=flows[s];f[0]+=int(w.trip_count);f[1]+=int(w.weekday_trip_count);f[2]+=int(w.holiday_trip_count);f[3]+=1
    db.close();out=pd.DataFrame([{'segment_id':s,'segment_flow_total':v[0],'segment_flow_weekday':v[1],'segment_flow_holiday':v[2],'route_traversals':v[3]} for s,v in flows.items()]).sort_values('segment_id')
    if len(out) and not (out.segment_flow_weekday+out.segment_flow_holiday==out.segment_flow_total).all():raise ValueError('segment day-type conservation failed')
    return out,records
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True);p.add_argument('--cache',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();o,r=aggregate(a.manifest,a.cache);a.output.parent.mkdir(parents=True,exist_ok=True);o.to_parquet(a.output,index=False);print(json.dumps({'segments':len(o),'route_records':len(r)}))
