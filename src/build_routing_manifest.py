"""Build the deterministic Phase 8.1 production and gate manifests."""
from __future__ import annotations
import argparse, hashlib, json, math
from pathlib import Path
import pandas as pd
try: from .route_segment_utils import route_cache_key
except ImportError: from route_segment_utils import route_cache_key

def sha256_file(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def stable_id(o,d): return hashlib.sha256(f"{o}->{d}".encode()).hexdigest()[:24]
def haversine(lon1,lat1,lon2,lat2):
    r=6371000; p1,p2=math.radians(lat1),math.radians(lat2); dp=math.radians(lat2-lat1); dl=math.radians(lon2-lon1)
    a=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*r*math.asin(math.sqrt(a))
def fp(frame,cols):
    b=frame[cols].astype(str).to_csv(index=False,lineterminator="\n").encode(); return hashlib.sha256(b).hexdigest()

def load_day_weights(root):
    parts=[]
    for p in sorted(Path(root).glob("day_type=*/hour=*/od.parquet")):
        d=pd.read_parquet(p,columns=["origin_station_id","destination_station_id","trip_count"])
        d["day_type"]=p.parent.parent.name.split("=",1)[1]; parts.append(d)
    if len(parts)!=48: raise ValueError(f"expected 48 authoritative hourly OD buckets, got {len(parts)}")
    g=pd.concat(parts,ignore_index=True).groupby(["origin_station_id","destination_station_id","day_type"],as_index=False).trip_count.sum()
    w=g.pivot(index=["origin_station_id","destination_station_id"],columns="day_type",values="trip_count").fillna(0).reset_index()
    return w.rename(columns={"weekday":"weekday_trip_count","holiday":"holiday_trip_count"})

def build(config, root):
    c=json.loads(Path(config).read_text(encoding="utf8")); root=Path(root)
    od=root/c["paths"]["od"]; co=root/c["paths"]["coordinates"]
    if sha256_file(od)!=c["locked_hashes"]["od"] or sha256_file(co)!=c["locked_hashes"]["coordinates"]: raise ValueError("locked input hash mismatch")
    o=pd.read_parquet(od); coords=pd.read_parquet(co)
    weights=load_day_weights(root/c["paths"]["hourly_od_root"])
    m=o.merge(weights,on=["origin_station_id","destination_station_id"],how="left",validate="one_to_one")
    if m[["weekday_trip_count","holiday_trip_count"]].isna().any().any(): raise ValueError("missing day-type weight")
    if not ((m.weekday_trip_count+m.holiday_trip_count)==m.trip_count).all(): raise ValueError("OD day-type decomposition mismatch")
    m=m[m.origin_station_id!=m.destination_station_id].copy()
    cm=coords.set_index("station_id")
    m=m[m.origin_station_id.isin(cm.index)&m.destination_station_id.isin(cm.index)].copy()
    for side in ("origin","destination"):
        m[f"{side}_lon"]=m[f"{side}_station_id"].map(cm.routing_lon);m[f"{side}_lat"]=m[f"{side}_station_id"].map(cm.routing_lat)
        m[f"{side}_coordinate_conflict"]=m[f"{side}_station_id"].map(cm.coordinate_conflict).astype(bool)
    m["route_id"]=[stable_id(a,b) for a,b in zip(m.origin_station_id,m.destination_station_id)]
    m["approx_distance_m"]=[haversine(*x) for x in zip(m.origin_lon,m.origin_lat,m.destination_lon,m.destination_lat)]
    env=c["environment"]; h=c["locked_hashes"]
    m["cache_key"]=[route_cache_key(origin_id=r.origin_station_id,destination_id=r.destination_station_id,origin_coordinate=(r.origin_lon,r.origin_lat),destination_coordinate=(r.destination_lon,r.destination_lat),brouter_version=env["brouter_version"],graph_hashes=h["graphs"],profile_hash=h["profile"],contract_version=c["routing_contract_version"],coordinate_artifact_hash=h["coordinates"],routing_parameters=env["routing_parameters"]) for r in m.itertuples()]
    m["coordinate_source"]="active_station_all.csv monthly coordinate"
    cols=["route_id","origin_station_id","destination_station_id","origin_lon","origin_lat","destination_lon","destination_lat","trip_count","weekday_trip_count","holiday_trip_count","origin_city","destination_city","origin_coordinate_conflict","destination_coordinate_conflict","coordinate_source","approx_distance_m","cache_key"]
    m=m[cols].sort_values(["origin_station_id","destination_station_id"]).reset_index(drop=True)
    ex=c["expected"]
    if len(m)!=ex["manifest_routes"] or int(m.trip_count.sum())!=ex["manifest_trip_weight"]: raise ValueError("production universe mismatch")
    if m.route_id.duplicated().any() or m.cache_key.duplicated().any(): raise ValueError("manifest key collision")
    return m,c

def select_gate(m,n):
    x=m.copy(); x["flow_bin"]=pd.qcut(x.trip_count.rank(method="first"),3,labels=["low","medium","high"])
    x["distance_bin"]=pd.qcut(x.approx_distance_m.rank(method="first"),3,labels=["short","medium","long"])
    x["geo_class"]=(x.origin_city+"->"+x.destination_city)
    x["selection_hash"]=[hashlib.sha256(f"gate-v1|{v}".encode()).hexdigest() for v in x.route_id]
    required=[]
    reciprocal=set(zip(x.destination_station_id,x.origin_station_id)); pairs=set(zip(x.origin_station_id,x.destination_station_id))
    x["reciprocal"]=[p in reciprocal for p in pairs]
    for _,g in x.groupby(["flow_bin","distance_bin","geo_class"],observed=True): required.append(g.sort_values("selection_hash").head(max(1,n//40)))
    for mask in [x.reciprocal, x.origin_coordinate_conflict|x.destination_coordinate_conflict]: required.append(x[mask].sort_values("selection_hash").head(30))
    out=pd.concat(required).drop_duplicates("route_id").sort_values("selection_hash").head(n)
    if len(out)<n: out=pd.concat([out,x[~x.route_id.isin(out.route_id)].sort_values("selection_hash").head(n-len(out))])
    return out[m.columns].sort_values("route_id").reset_index(drop=True)

def main(a):
    m,c=build(a.config,a.root); out=Path(a.output or Path(a.root)/c["paths"]["manifest"]); out.parent.mkdir(parents=True,exist_ok=True);m.to_parquet(out,index=False)
    gate=select_gate(m,a.gate_size); gp=Path(a.gate_output);gp.parent.mkdir(parents=True,exist_ok=True);gate.to_parquet(gp,index=False)
    receipt={"manifest":{"rows":len(m),"trip_weight":int(m.trip_count.sum()),"weekday":int(m.weekday_trip_count.sum()),"holiday":int(m.holiday_trip_count.sum()),"sha256":sha256_file(out),"fingerprint":fp(m,["route_id","cache_key","trip_count","weekday_trip_count","holiday_trip_count"])},"gate":{"rows":len(gate),"sha256":sha256_file(gp)}}
    Path(a.receipt).write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf8");print(json.dumps(receipt))
if __name__=="__main__":
    r=Path(__file__).resolve().parents[1];p=argparse.ArgumentParser();p.add_argument("--root",type=Path,default=r);p.add_argument("--config",type=Path,default=r/"config/brouter_production.yaml");p.add_argument("--output",type=Path);p.add_argument("--gate-size",type=int,default=1000);p.add_argument("--gate-output",type=Path,default=r/"data/processed/routing/production/gate_manifest.parquet");p.add_argument("--receipt",type=Path,default=r/"data/processed/routing/production/manifest_receipt.json");main(p.parse_args())
