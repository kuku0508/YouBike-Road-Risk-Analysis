"""Phase 8.5A accident severity reconstruction and segment-level risk inputs.

Produces unsmoothed microsegment inputs only. It does not rank or label hotspots.
"""
from __future__ import annotations
import argparse, hashlib, json, math, sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd

try:
    from .match_accidents_to_brouter_segments import stable_receipt_fingerprint
    from .validate_accident_road_reference import SpatialContractError, atomic_json, atomic_parquet, sha256_file
except ImportError:
    from match_accidents_to_brouter_segments import stable_receipt_fingerprint
    from validate_accident_road_reference import SpatialContractError, atomic_json, atomic_parquet, sha256_file

CONTRACT_VERSION="segment-risk-inputs-v1"
FATAL_WEIGHT=193; INJURY_WEIGHT=117
ENTITY_PATH="data/processed/accidents/accident_entities_2023_2024.parquet"
MATCH_PATH="data/processed/accidents/accident_brouter_segment_matches_2023_2024.parquet"
EXPOSURE_PATH="data/processed/routing/direction_neutral_segment_exposure_2023_2024.parquet"
OUTPUT_PATH="data/processed/risk/segment_risk_inputs_2023_2024.parquet"
EXPECTED_ENTITY_SHA="3b82df95f59e5725c84c4f05fff7c785795f66d3e76b7580108a598613497d29"
EXPECTED_ENTITY_FP="ded355d1b5791ea3f2146c51d0321984b4d75ba9e0ff17fb20b8cf9a7b210923"
EXPECTED_MATCH_SHA="bdad7b3190f27991c15dd5860a9792b41ca7a545352e1b37ec2e59361a2e2baf"
EXPECTED_MATCH_FP="db598989c4b0278fdec77d35b7fb9ef10c5d139ba267e5f67f7620c72d687658"
EXPECTED_EXPOSURE_SHA="c6dd301a7b328d650aa4e58a7e9b36330d6389465594ad69010d39c02dd0cd6f"
EXPECTED_EXPOSURE_FP="d494a2ddc33e76dc169454af08996ae91543bea6a540a06832d3ede9d4cfad88"
EXPECTED_84B_RECEIPT_FP="e465bf6b34adad2bce14563421ab21a44297b0bbaaa5ff2583c5a230a7ba6a4f"
CALENDAR_SHA="a10889e9a656d9f9c06975f0e1adb36b3b6d93955365bd91fc49308a2dd37bc5"
INT_COLUMNS=["fatal_accident_count","injury_accident_count","accident_count","weekday_fatal_accident_count","weekday_injury_accident_count","weekday_accident_count","holiday_fatal_accident_count","holiday_injury_accident_count","holiday_accident_count","epdo","weekday_epdo","holiday_epdo"]

def classify_severity(death,death_2_30,injury,missing=False):
    values=(death,death_2_30,injury)
    if missing or any(pd.isna(v) for v in values): return "severity_unavailable",None
    d,d30,i=(float(v) for v in values)
    if min(d,d30,i)<0 or any(not x.is_integer() for x in (d,d30,i)): return "inconsistent_source_fields",None
    if d>0 or d30>0: return "classified_fatal",FATAL_WEIGHT
    if i>0: return "classified_injury",INJURY_WEIGHT
    return "severity_unavailable",None

def reconstruct_severity(entities):
    rows=[]
    for r in entities.sort_values("reconstructed_accident_id").itertuples(index=False):
        status,contribution=classify_severity(r.death_count,r.death_2_30_day_count,r.injury_count,r.severity_missing)
        rows.append({"reconstructed_accident_id":r.reconstructed_accident_id,"severity_status":status,"severity_class":"fatal" if status=="classified_fatal" else "injury" if status=="classified_injury" else None,"epdo_contribution":contribution})
    return pd.DataFrame(rows)

def attach_day_type(matches,calendar):
    out=matches.copy(); dates=pd.to_datetime(out.event_datetime,errors="coerce").dt.date
    if dates.isna().any(): raise SpatialContractError("invalid accident event date")
    mapping=dict(zip(calendar.Date,calendar.IsHoliday,strict=True)); flags=dates.map(mapping)
    if flags.isna().any(): raise SpatialContractError("accident date missing from authoritative calendar")
    out["day_type"]=flags.map({0:"weekday",1:"holiday"})
    return out

def safe_rate(numerator,denominator):
    n=np.asarray(numerator,dtype=float); d=np.asarray(denominator,dtype=float); out=np.full(len(n),np.nan); np.divide(n*1000.0,d,out=out,where=d>0); return out

def build_segment_table(exposure,eligible):
    base=exposure.rename(columns={"bidirectional_total_trip_weight":"total_trip_weight","bidirectional_weekday_trip_weight":"weekday_trip_weight","bidirectional_holiday_trip_weight":"holiday_trip_weight"}).copy()
    eligible=eligible.copy(); eligible["fatal"]=(eligible.severity_class=="fatal").astype("int64"); eligible["injury"]=(eligible.severity_class=="injury").astype("int64")
    eligible["weekday_fatal"]=((eligible.day_type=="weekday")&(eligible.severity_class=="fatal")).astype("int64"); eligible["weekday_injury"]=((eligible.day_type=="weekday")&(eligible.severity_class=="injury")).astype("int64")
    eligible["holiday_fatal"]=((eligible.day_type=="holiday")&(eligible.severity_class=="fatal")).astype("int64"); eligible["holiday_injury"]=((eligible.day_type=="holiday")&(eligible.severity_class=="injury")).astype("int64")
    agg=eligible.groupby("assigned_physical_segment_id",sort=True)[["fatal","injury","weekday_fatal","weekday_injury","holiday_fatal","holiday_injury"]].sum()
    out=base.merge(agg,left_on="physical_segment_id",right_index=True,how="left",validate="one_to_one")
    for c in ["fatal","injury","weekday_fatal","weekday_injury","holiday_fatal","holiday_injury"]: out[c]=out[c].fillna(0).astype("int64")
    out=out.rename(columns={"fatal":"fatal_accident_count","injury":"injury_accident_count","weekday_fatal":"weekday_fatal_accident_count","weekday_injury":"weekday_injury_accident_count","holiday_fatal":"holiday_fatal_accident_count","holiday_injury":"holiday_injury_accident_count"})
    out["accident_count"]=out.fatal_accident_count+out.injury_accident_count
    out["weekday_accident_count"]=out.weekday_fatal_accident_count+out.weekday_injury_accident_count
    out["holiday_accident_count"]=out.holiday_fatal_accident_count+out.holiday_injury_accident_count
    out["epdo"]=FATAL_WEIGHT*out.fatal_accident_count+INJURY_WEIGHT*out.injury_accident_count
    out["weekday_epdo"]=FATAL_WEIGHT*out.weekday_fatal_accident_count+INJURY_WEIGHT*out.weekday_injury_accident_count
    out["holiday_epdo"]=FATAL_WEIGHT*out.holiday_fatal_accident_count+INJURY_WEIGHT*out.holiday_injury_accident_count
    max_n=int(out.accident_count.max()); max_e=int(out.epdo.max())
    out["sri"]=out.accident_count/max_n if max_n else 0.0; out["ssi"]=out.epdo/max_e if max_e else 0.0; out["cbi"]=out.sri+out.ssi
    out["epdo_per_1000_trips"]=safe_rate(out.epdo,out.total_trip_weight)
    out["weekday_epdo_per_1000_trips"]=safe_rate(out.weekday_epdo,out.weekday_trip_weight)
    out["holiday_epdo_per_1000_trips"]=safe_rate(out.holiday_epdo,out.holiday_trip_weight)
    weekday_median=float(out.weekday_trip_weight.median()); holiday_median=float(out.holiday_trip_weight.median())
    out["weekday_high_flow"]=(out.weekday_trip_weight>=weekday_median); out["holiday_high_flow"]=(out.holiday_trip_weight>=holiday_median)
    out["pdo_accidents_available"]=False; out["epdo_pdo_component_status"]="unobserved"; out["accident_population"]="fatal_and_injury_accidents_only"
    out["source_accident_entity_fingerprint"]=EXPECTED_ENTITY_FP; out["source_matching_fingerprint"]=EXPECTED_MATCH_FP; out["source_exposure_fingerprint"]=EXPECTED_EXPOSURE_FP; out["contract_version"]=CONTRACT_VERSION
    return out.sort_values("physical_segment_id").reset_index(drop=True),weekday_median,holiday_median

def frame_fingerprint(frame):
    d=hashlib.sha256()
    for row in frame.sort_values("physical_segment_id").itertuples(index=False,name=None):
        vals=[]
        for v in row:
            if v is None or pd.isna(v): vals.append(None)
            elif isinstance(v,float): vals.append(format(v,".12g"))
            elif hasattr(v,"item"): vals.append(v.item())
            else: vals.append(v)
        d.update((json.dumps(vals,ensure_ascii=False,separators=(",",":"))+"\n").encode())
    return d.hexdigest()

def numeric_summary(values):
    s=pd.Series(values).dropna().astype(float)
    if s.empty:return {"count":0}
    q=s.quantile([.25,.5,.75,.9,.95,.99]); return {"count":int(len(s)),"min":float(s.min()),"p25":float(q.loc[.25]),"p50":float(q.loc[.5]),"p75":float(q.loc[.75]),"p90":float(q.loc[.9]),"p95":float(q.loc[.95]),"p99":float(q.loc[.99]),"max":float(s.max())}

def load_calendar_contract(root):
    sys.path.insert(0,str(root/"src")); from reconstruct_hourly_sna_features import load_calendar
    cfg=json.loads((root/"config/hourly_sna_feature_contract.yaml").read_text(encoding="utf8")); source=root/cfg["calendar"]["source"]
    return load_calendar(source,CALENDAR_SHA,Path(r"C:\Program Files\R\R-4.5.2\bin\Rscript.exe"),root/"src/export_fst_calendar.R")

def load_inputs(root):
    r84=json.loads((root/"notes/phase8_4b-accident-brouter-matching.json").read_text(encoding="utf8"))
    if r84["receipt_fingerprint_sha256"]!=EXPECTED_84B_RECEIPT_FP or stable_receipt_fingerprint(r84)!=EXPECTED_84B_RECEIPT_FP: raise SpatialContractError("Phase 8.4B receipt mismatch")
    paths=[(root/ENTITY_PATH,EXPECTED_ENTITY_SHA),(root/MATCH_PATH,EXPECTED_MATCH_SHA),(root/EXPOSURE_PATH,EXPECTED_EXPOSURE_SHA)]
    for p,h in paths:
        if sha256_file(p)!=h: raise SpatialContractError(f"locked SHA mismatch: {p}")
    entities=pd.read_parquet(paths[0][0]); matches=pd.read_parquet(paths[1][0]); exposure=pd.read_parquet(paths[2][0])
    if len(entities)!=46586 or len(matches)!=46586 or len(exposure)!=106049: raise SpatialContractError("locked row count mismatch")
    if set(entities.reconstructed_accident_id)!=set(matches.reconstructed_accident_id): raise SpatialContractError("accident ID set mismatch")
    return entities,matches,exposure,r84

def validate_output(out,eligible):
    if len(out)!=106049 or not out.physical_segment_id.is_unique: raise SpatialContractError("segment universe invariant failed")
    if not (out.accident_count==out.fatal_accident_count+out.injury_accident_count).all(): raise SpatialContractError("accident sum failed")
    if not (out.weekday_accident_count+out.holiday_accident_count==out.accident_count).all(): raise SpatialContractError("day-type accident conservation failed")
    if not (out.weekday_epdo+out.holiday_epdo==out.epdo).all(): raise SpatialContractError("day-type EPDO conservation failed")
    if int(out.accident_count.sum())!=len(eligible) or int(out.epdo.sum())!=FATAL_WEIGHT*int((eligible.severity_class=="fatal").sum())+INJURY_WEIGHT*int((eligible.severity_class=="injury").sum()): raise SpatialContractError("aggregation conservation failed")
    if out.cbi.min()<0 or out.cbi.max()>2+1e-12 or not math.isclose(out.sri.max(),1) or not math.isclose(out.ssi.max(),1): raise SpatialContractError("CBI normalization failed")

def execute(root,output,receipt_path):
    entities,matches,exposure,r84=load_inputs(root); calendar,calendar_audit=load_calendar_contract(root)
    severity=reconstruct_severity(entities); joined=matches.merge(severity,on="reconstructed_accident_id",validate="one_to_one"); joined=attach_day_type(joined,calendar)
    classified=joined.severity_status.isin(["classified_fatal","classified_injury"]); matched=joined.match_status.isin(["matched_context","matched_global"]); eligible=joined[classified&matched].copy()
    out,wmed,hmed=build_segment_table(exposure,eligible); validate_output(out,eligible); atomic_parquet(output,out)
    sev=severity.severity_status.value_counts().to_dict(); matched_sev=eligible.severity_class.value_counts().to_dict(); day=eligible.day_type.value_counts().to_dict()
    receipt={"contract_version":CONTRACT_VERSION,"generated_at_utc":datetime.now(timezone.utc).isoformat(timespec="seconds"),"locked_inputs":{"entity_sha256":EXPECTED_ENTITY_SHA,"entity_fingerprint":EXPECTED_ENTITY_FP,"matching_sha256":EXPECTED_MATCH_SHA,"matching_fingerprint":EXPECTED_MATCH_FP,"exposure_sha256":EXPECTED_EXPOSURE_SHA,"exposure_fingerprint":EXPECTED_EXPOSURE_FP,"phase8_4b_receipt_fingerprint":EXPECTED_84B_RECEIPT_FP,"calendar_sha256":CALENDAR_SHA},
      "severity_contract":{"fatal":"death_count > 0 OR death_2_30_day_count > 0","injury":"both death counts = 0 AND injury_count > 0","fatal_precedence":True,"death_2_30_day_as_fatal":"analytical_decision","coefficients":{"fatal":193,"injury":117,"pdo":1},"pdo_accidents_available":False,"epdo_pdo_component_status":"unobserved","accident_population":"fatal_and_injury_accidents_only"},
      "severity":{"canonical_accidents":len(severity),"status_counts":{k:int(v) for k,v in sorted(sev.items())},"conservation":sum(sev.values())==46586},
      "matching_intersection":{"phase8_4b_matched":int(matched.sum()),"matched_classified":len(eligible),"matched_fatal":int(matched_sev.get("fatal",0)),"matched_injury":int(matched_sev.get("injury",0)),"excluded_from_segment_aggregation":46586-len(eligible)},
      "day_type":{"weekday_matched":int(day.get("weekday",0)),"holiday_matched":int(day.get("holiday",0)),"unresolved":0,"calendar_audit":calendar_audit},
      "segment_universe":{"rows":len(out),"with_accidents":int((out.accident_count>0).sum()),"without_accidents":int((out.accident_count==0).sum()),"max_accident_count":int(out.accident_count.max()),"max_epdo":int(out.epdo.max())},
      "epdo":{"total":int(out.epdo.sum()),"weekday":int(out.weekday_epdo.sum()),"holiday":int(out.holiday_epdo.sum()),"conservation":int(out.weekday_epdo.sum()+out.holiday_epdo.sum())==int(out.epdo.sum())},
      "cbi":{"max_sri":float(out.sri.max()),"max_ssi":float(out.ssi.max()),"distribution":numeric_summary(out.cbi),"common_normalization_universe":len(out),"day_type_renormalization":False},
      "exposure":{"total":int(out.total_trip_weight.sum()),"weekday":int(out.weekday_trip_weight.sum()),"holiday":int(out.holiday_trip_weight.sum()),"total_median":float(out.total_trip_weight.median()),"weekday_median":wmed,"holiday_median":hmed,"weekday_high_flow_segments":int(out.weekday_high_flow.sum()),"holiday_high_flow_segments":int(out.holiday_high_flow.sum()),"zero_total":int((out.total_trip_weight==0).sum()),"zero_weekday":int((out.weekday_trip_weight==0).sum()),"zero_holiday":int((out.holiday_trip_weight==0).sum())},
      "rates":{"total":numeric_summary(out.epdo_per_1000_trips),"weekday":numeric_summary(out.weekday_epdo_per_1000_trips),"holiday":numeric_summary(out.holiday_epdo_per_1000_trips),"segments_with_accidents_exposure":numeric_summary(out.loc[out.accident_count>0,"total_trip_weight"]),"segments_without_accidents_exposure":numeric_summary(out.loc[out.accident_count==0,"total_trip_weight"])},
      "validation":{"accident_conservation":True,"epdo_conservation":True,"day_type_conservation":True,"id_uniqueness":True,"no_ranking_performed":True,"unsmoothed_microsegments":True},
      "output":{"path":output.relative_to(root).as_posix(),"rows":len(out),"fingerprint_sha256":frame_fingerprint(out),"parquet_sha256":sha256_file(output)},
      "limitations":{"pdo":"A3/PDO-only accidents unavailable; PDO component unobserved, not observed zero","exposure":"BRouter reconstructed estimated traversal exposure, not GPS-observed counts or unique cyclists","geometry":"unsmoothed routing microsegments; no corridor merge or Road.shp aggregation"},
      "readiness":{"phase8_5b":"READY_FOR_SEPARATELY_AUTHORIZED_STABILITY_AND_PRESENTATION_POLICY"}}
    receipt["receipt_fingerprint_sha256"]=stable_receipt_fingerprint(receipt); atomic_json(receipt_path,receipt); return receipt

def main():
    root=Path(__file__).resolve().parents[1]; p=argparse.ArgumentParser(); p.add_argument("--root",type=Path,default=root); a=p.parse_args(); r=execute(a.root.resolve(),a.root/OUTPUT_PATH,a.root/"notes/phase8_5a-risk-input-contract.json"); print(json.dumps({"severity":r["severity"],"matched":r["matching_intersection"],"segments":r["segment_universe"]},ensure_ascii=False))
if __name__=="__main__":main()
