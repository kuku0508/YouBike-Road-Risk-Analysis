"""Phase 8.5B descriptive microsegment risk stability audit; never ranks segments."""
from __future__ import annotations
import argparse, hashlib, json, math
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
from pyproj import Transformer

try:
    from .build_segment_risk_inputs import frame_fingerprint
    from .match_accidents_to_brouter_segments import stable_receipt_fingerprint
    from .validate_accident_road_reference import SpatialContractError, atomic_json, sha256_file
except ImportError:
    from build_segment_risk_inputs import frame_fingerprint
    from match_accidents_to_brouter_segments import stable_receipt_fingerprint
    from validate_accident_road_reference import SpatialContractError, atomic_json, sha256_file

INPUT_PATH="data/processed/risk/segment_risk_inputs_2023_2024.parquet"
EXPECTED_ROWS=106_049
EXPECTED_FP="f9a3f6ba149cf8bdd4742d5e5857e03aa0a4bb8a1ab90f603199e10f103c4f14"
EXPECTED_SHA="dec4bf536fe692e69311371e02c905e02e19bdc49e30f45f88316e8dffcc750f"
EXPECTED_RECEIPT_FP="549e5344dab77b3fbb25df534ff45466734bfad49428c4c543cfaa7ed8c0fd70"
CONTRACT_VERSION="microsegment-risk-stability-audit-v1"

def validate_locked_input(prior, parquet_sha, content_fingerprint, rows):
    if stable_receipt_fingerprint(prior)!=EXPECTED_RECEIPT_FP or prior.get("receipt_fingerprint_sha256")!=EXPECTED_RECEIPT_FP:
        raise SpatialContractError("Phase 8.5A receipt mismatch")
    if parquet_sha!=EXPECTED_SHA:
        raise SpatialContractError("Phase 8.5A Parquet SHA mismatch")
    if content_fingerprint!=EXPECTED_FP:
        raise SpatialContractError("Phase 8.5A content fingerprint mismatch")
    if rows!=EXPECTED_ROWS:
        raise SpatialContractError("Phase 8.5A row count mismatch")

def segment_lengths(frame):
    transformer=Transformer.from_crs(4326,3826,always_xy=True); values=[]
    for r in frame.itertuples(index=False):
        x1,y1=transformer.transform(r.endpoint1_lon_e6/1e6,r.endpoint1_lat_e6/1e6); x2,y2=transformer.transform(r.endpoint2_lon_e6/1e6,r.endpoint2_lat_e6/1e6)
        length=math.hypot(x2-x1,y2-y1)
        if not math.isfinite(length) or length<=0: raise SpatialContractError("non-positive or non-finite microsegment length")
        values.append(length)
    return pd.Series(values,index=frame.index,name="segment_length_m")

def stats(values,quantiles=(.01,.05,.1,.25,.5,.75,.9,.95,.975,.99,.995)):
    s=pd.Series(values).dropna().astype(float); result={"n":int(len(s)),"nonzero_n":int((s>0).sum())}
    if s.empty:return result
    result.update(min=float(s.min()),mean=float(s.mean()),max=float(s.max()))
    for q in quantiles: result[f"p{q*100:g}"]=float(s.quantile(q))
    return result

def reduction(full,filtered):
    out={}
    for k in ("p95","p99","max"):
        a=float(full[k]); b=float(filtered[k]); out[k]={"full":a,"high_flow":b,"ratio":None if a==0 else b/a,"reduction_pct":None if a==0 else (1-b/a)*100}
    return out

def quartile_labels(values):
    s=pd.Series(values).astype(float); cuts=[float(s.quantile(q)) for q in (.25,.5,.75)]
    if not (cuts[0]<=cuts[1]<=cuts[2]): raise SpatialContractError("invalid quartile thresholds")
    labels=np.searchsorted(np.array(cuts),s.to_numpy(),side="left")+1
    return pd.Series([f"Q{x}" for x in labels],index=s.index),cuts

def tail_diag(frame,rate_col,exposure_col,length_col,threshold):
    sub=frame[frame[rate_col].notna() & (frame[rate_col]>=threshold)]
    return {"n":len(sub),"threshold":float(threshold),"accident_count":stats(sub.accident_count,(.5,.75,.9)),"epdo":stats(sub.epdo,(.5,.75,.9)),"exposure":stats(sub[exposure_col],(.1,.25,.5,.75,.9)),"segment_length_m":stats(sub[length_col],(.1,.25,.5,.75,.9)),"cbi":stats(sub.cbi,(.5,.75,.9))}

def exposure_quartiles(frame,exposure_col,rate_col):
    sub=frame[frame[exposure_col]>0].copy(); sub["quartile"],cuts=quartile_labels(sub[exposure_col]); groups={}
    for q,g in sub.groupby("quartile",sort=True): groups[q]={"n":len(g),"segments_with_accidents":int((g.accident_count>0).sum()),"rate":stats(g[rate_col],(.5,.9,.95,.99))}
    return {"cut_points":cuts,"groups":groups}

def length_quartiles(frame,rate_col):
    sub=frame.copy(); sub["quartile"],cuts=quartile_labels(sub.segment_length_m); groups={}
    for q,g in sub.groupby("quartile",sort=True): groups[q]={"n":len(g),"segments_with_accidents":int((g.accident_count>0).sum()),"rate":stats(g[rate_col],(.5,.9,.95,.99))}
    return {"cut_points":cuts,"groups":groups}

def joint_matrix(frame,exposure_col,rate_col):
    sub=frame[frame[exposure_col]>0].copy(); sub["exposure_q"],ec=quartile_labels(sub[exposure_col]); sub["length_q"],lc=quartile_labels(sub.segment_length_m); cells={}
    for (eq,lq),g in sub.groupby(["exposure_q","length_q"],sort=True): cells[f"{eq}x{lq}"]={"n":len(g),"segments_with_accidents":int((g.accident_count>0).sum()),"median_rate":float(g[rate_col].median()),"p95_rate":float(g[rate_col].quantile(.95)),"p99_rate":float(g[rate_col].quantile(.99))}
    return {"exposure_cut_points":ec,"length_cut_points":lc,"cells":cells}

def presence_exposure(frame,col):
    return {"with_accidents":stats(frame.loc[frame.accident_count>0,col],(.1,.25,.5,.75,.9,.95,.99)),"without_accidents":stats(frame.loc[frame.accident_count==0,col],(.1,.25,.5,.75,.9,.95,.99))}

def audit(frame):
    if len(frame)!=EXPECTED_ROWS or not frame.physical_segment_id.is_unique: raise SpatialContractError("segment universe mismatch")
    forbidden=[c for c in frame.columns if "rank" in c.lower() or "hotspot" in c.lower() or "minimum_exposure" in c.lower()]
    if forbidden: raise SpatialContractError(f"forbidden upstream policy fields: {forbidden}")
    f=frame.copy(); f["segment_length_m"]=segment_lengths(f)
    length={"all":stats(f.segment_length_m),"by_accident_presence":{"with_accidents":stats(f.loc[f.accident_count>0,"segment_length_m"],(.1,.25,.5,.75,.9,.95,.99)),"without_accidents":stats(f.loc[f.accident_count==0,"segment_length_m"],(.1,.25,.5,.75,.9,.95,.99))},"weekday_high_flow":{"true":stats(f.loc[f.weekday_high_flow,"segment_length_m"]),"false":stats(f.loc[~f.weekday_high_flow,"segment_length_m"])},"holiday_high_flow":{"true":stats(f.loc[f.holiday_high_flow,"segment_length_m"]),"false":stats(f.loc[~f.holiday_high_flow,"segment_length_m"])}}
    views={"total_baseline":{"full_rate":stats(f.epdo_per_1000_trips)}}
    for day in ("weekday","holiday"):
        rate=f"{day}_epdo_per_1000_trips"; exposure=f"{day}_trip_weight"; flag=f"{day}_high_flow"
        full=stats(f[rate]); high=stats(f.loc[f[flag]&f[rate].notna(),rate]); p99=float(pd.Series(f[rate]).dropna().quantile(.99)); hp99=float(f.loc[f[flag]&f[rate].notna(),rate].quantile(.99))
        views[day]={"full_rate":full,"high_flow_rate":high,"reduction":reduction(full,high),"full_p99_tail":tail_diag(f,rate,exposure,"segment_length_m",p99),"high_flow_p99_tail":tail_diag(f[f[flag]],rate,exposure,"segment_length_m",hp99),"exposure_quartiles":exposure_quartiles(f,exposure,rate),"length_quartiles":length_quartiles(f,rate),"joint_exposure_length":joint_matrix(f,exposure,rate),"cbi_high_flow":stats(f.loc[f[flag],"cbi"],(.5,.75,.9,.95,.99))}
    zero=int((f.cbi==0).sum()); nonzero=int((f.cbi>0).sum())
    cbi={"zero_count":zero,"zero_pct":zero/len(f),"nonzero_count":nonzero,"nonzero_pct":nonzero/len(f),"nonzero_distribution":stats(f.loc[f.cbi>0,"cbi"],(.1,.25,.5,.75,.9,.95,.99))}
    return f,{"segment_count":len(f),"segment_length":length,"rate_views":views,"exposure_by_accident_presence":{c:presence_exposure(f,c) for c in ["total_trip_weight","weekday_trip_weight","holiday_trip_weight"]},"cbi_sparsity":cbi,"no_ranking":True,"no_new_cutoff":True}

def audit_fingerprint(payload):
    return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()

def execute(root,receipt_path):
    prior=json.loads((root/"notes/phase8_5a-risk-input-contract.json").read_text(encoding="utf8"))
    path=root/prior["output"]["path"]
    frame=pd.read_parquet(path)
    validate_locked_input(prior,sha256_file(path),frame_fingerprint(frame),len(frame))
    _,qa=audit(frame)
    receipt={"contract_version":CONTRACT_VERSION,"generated_at_utc":datetime.now(timezone.utc).isoformat(timespec="seconds"),"locked_input":{"path":prior["output"]["path"],"rows":EXPECTED_ROWS,"fingerprint_sha256":EXPECTED_FP,"parquet_sha256":EXPECTED_SHA,"receipt_fingerprint_sha256":EXPECTED_RECEIPT_FP},"length_contract":{"source":"canonical endpoint microdegrees","source_crs":"EPSG:4326","target_crs":"EPSG:3826","geometry":"straight LineString between adjacent routing endpoints","official_road_length":False},"qa":qa,"stability_conclusion":"supported","additional_stability_policy_required":False,"interpretation":{"scope":"descriptive presentation-universe evidence; not statistical optimality and not a hotspot policy","low_exposure_drives_raw_extremes":True,"short_microsegments_materially_drive_high_flow_extremes":False,"extreme_values_remain_after_filtering":True,"cbi_linear_scale_compression_risk":True},"prohibited_work_confirmed_not_performed":{"ranking":False,"hotspot":False,"new_exposure_cutoff":False,"corridor_aggregation":False,"spatial_smoothing":False,"per_distance_metric":False,"phase8_5c":False}}
    receipt["qa_fingerprint_sha256"]=audit_fingerprint({"length_contract":receipt["length_contract"],"qa":qa}); receipt["receipt_fingerprint_sha256"]=stable_receipt_fingerprint(receipt); atomic_json(receipt_path,receipt); return receipt

def main():
    root=Path(__file__).resolve().parents[1]; p=argparse.ArgumentParser(); p.add_argument("--root",type=Path,default=root); a=p.parse_args(); r=execute(a.root.resolve(),a.root/"notes/phase8_5b-stability-audit.json"); print(json.dumps({"segments":r["qa"]["segment_count"],"qa_fingerprint":r["qa_fingerprint_sha256"]},ensure_ascii=False))
if __name__=="__main__":main()
