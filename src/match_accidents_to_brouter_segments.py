"""Phase 8.4B formal accident-to-direction-neutral BRouter segment matching."""
from __future__ import annotations
import argparse, hashlib, json, math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

try:
    from .validate_accident_brouter_candidates import (
        ACCIDENT_PATH, BOUNDED_PATH, DIRECTED_COLUMNS, DIRECTED_PATH, EXPECTED_ACCIDENT_FP,
        EXPECTED_ACCIDENT_SHA, EXPECTED_DIRECTED_FP, EXPECTED_DIRECTED_SHA, NEUTRAL_PATH,
        OUTPUT_PATH as CANDIDATE_PATH, SpatialContractError, atomic_json, atomic_parquet,
        build_neutral_segments, directed_fingerprint, neutral_fingerprint, output_fingerprint as candidate_fingerprint,
        segment_key, sha256_file,
    )
    from .finalize_accident_road_context import final_output_fingerprint
except ImportError:
    from validate_accident_brouter_candidates import *
    from finalize_accident_road_context import final_output_fingerprint

CONTRACT_VERSION="accident-brouter-formal-matching-v1"
PRIMARY_THRESHOLD_M=10.0
EXPECTED_NEUTRAL_FP="94b6de3529ac2b989d288ba4a67f58e8b7f23face25275881b01d2983e853496"
EXPECTED_NEUTRAL_SHA="8655af1ab1895820a6da53ceaeb32e5b73c200dcc7d01874d5fb782a5c52c0c3"
EXPECTED_CANDIDATE_FP="53f1e8e741cb1269299db885a8d5b5794f5a444b39b260f878434ce57c7758e6"
EXPECTED_CANDIDATE_SHA="8e1de7f64eb21884a2ce53e7cae2ff16f0e97f8d233d5be36ef0f995fd612233"
EXPOSURE_PATH="data/processed/routing/direction_neutral_segment_exposure_2023_2024.parquet"
MATCH_PATH="data/processed/accidents/accident_brouter_segment_matches_2023_2024.parquet"
MATCH_COLUMNS=["reconstructed_accident_id","year","event_datetime","road_context_status","match_status","match_basis",
 "assigned_endpoint1_lon_e6","assigned_endpoint1_lat_e6","assigned_endpoint2_lon_e6","assigned_endpoint2_lat_e6","assigned_physical_segment_id",
 "nearest_distance_m","second_nearest_distance_m","distance_gap_m","minimum_distance_candidate_count","road_context_constrained",
 "directional_member_count","bidirectional_total_trip_weight","bidirectional_weekday_trip_weight","bidirectional_holiday_trip_weight",
 "source_accident_context_fingerprint","source_candidate_validation_fingerprint","source_direction_neutral_fingerprint"]

def stable_receipt_fingerprint(r):
    x={k:v for k,v in r.items() if k not in {"generated_at_utc","receipt_fingerprint_sha256"}}
    return hashlib.sha256(json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode()).hexdigest()

def parse_key(value):
    try:
        a,b=value.split("|"); x=tuple(map(int,a.split(",")+b.split(",")))
    except Exception as e: raise SpatialContractError(f"malformed physical segment key: {value}") from e
    if len(x)!=4 or (x[0],x[1]) >= (x[2],x[3]): raise SpatialContractError("noncanonical physical segment key")
    return x

def build_exposure(directed):
    if list(directed.columns)!=DIRECTED_COLUMNS: raise SpatialContractError("directed schema mismatch")
    grouped={}
    for r in directed.itertuples(index=False):
        a=(int(r.from_lon_e6),int(r.from_lat_e6)); b=(int(r.to_lon_e6),int(r.to_lat_e6)); lo,hi=sorted((a,b)); key=(*lo,*hi)
        if lo==hi: raise SpatialContractError("zero-length directed segment")
        old=grouped.get(key,[0,0,0,0]); old[0]+=1; old[1]+=int(r.total_trip_weight); old[2]+=int(r.weekday_trip_weight); old[3]+=int(r.holiday_trip_weight); grouped[key]=old
    rows=[]
    for key,v in sorted(grouped.items()):
        if v[0] not in (1,2) or v[1]!=v[2]+v[3] or min(v[1:])<0: raise SpatialContractError("direction-neutral exposure invariant failed")
        rows.append({"physical_segment_id":segment_key(key),"endpoint1_lon_e6":key[0],"endpoint1_lat_e6":key[1],"endpoint2_lon_e6":key[2],"endpoint2_lat_e6":key[3],"directional_member_count":v[0],"bidirectional_total_trip_weight":v[1],"bidirectional_weekday_trip_weight":v[2],"bidirectional_holiday_trip_weight":v[3]})
    out=pd.DataFrame(rows)
    expected=(int(directed.total_trip_weight.sum()),int(directed.weekday_trip_weight.sum()),int(directed.holiday_trip_weight.sum()))
    actual=tuple(int(out[c].sum()) for c in ["bidirectional_total_trip_weight","bidirectional_weekday_trip_weight","bidirectional_holiday_trip_weight"])
    if actual!=expected: raise SpatialContractError("direction-neutral exposure conservation failed")
    return out,expected

def choose_evidence(row):
    status=row.road_context_status
    if status in {"contained_valid_road","contained_blank_road_id"}:
        return True,row.context_candidate_count,row.context_nearest_segment_key,row.context_nearest_distance_m,row.context_second_distance_m,row.context_distance_gap_m,row.context_exact_tie_count
    if status=="outside_reference_coverage":
        return False,None,row.global_nearest_segment_key,row.global_nearest_distance_m,row.global_second_distance_m,row.global_distance_gap_m,row.global_exact_tie_count
    if status=="coordinate_unavailable": return False,None,None,None,None,None,None
    if status=="contained_multiple": return True,None,None,None,None,None,None
    raise SpatialContractError(f"unknown road context: {status}")

def classify(row,threshold=PRIMARY_THRESHOLD_M):
    constrained,count,key,d1,d2,gap,ties=choose_evidence(row)
    if row.road_context_status=="coordinate_unavailable": return "coordinate_unavailable","none",None,(d1,d2,gap,ties,constrained)
    if row.road_context_status=="contained_multiple": return "contained_multiple_unresolved","none",None,(d1,d2,gap,ties,constrained)
    if constrained and int(count)==0: return "context_no_brouter_candidate","none",None,(d1,d2,gap,ties,constrained)
    if key is None or d1 is None or not math.isfinite(float(d1)): raise SpatialContractError("eligible context lacks nearest evidence")
    if float(d1)>threshold: return "unmatched_distance","none",None,(d1,d2,gap,ties,constrained)
    if int(ties)>1: return "ambiguous_exact_tie","none",None,(d1,d2,gap,ties,constrained)
    return ("matched_context","road_context_constrained",key,(d1,d2,gap,ties,constrained)) if constrained else ("matched_global","global_outside_reference",key,(d1,d2,gap,ties,constrained))

def matching_fingerprint(frame):
    d=hashlib.sha256()
    for row in frame.sort_values("reconstructed_accident_id")[MATCH_COLUMNS].itertuples(index=False,name=None):
        vals=[]
        for v in row:
            if v is None or pd.isna(v): vals.append(None)
            elif isinstance(v,float): vals.append(format(v,".12g"))
            elif hasattr(v,"item"): vals.append(v.item())
            else: vals.append(v)
        d.update((json.dumps(vals,ensure_ascii=False,separators=(",",":"))+"\n").encode())
    return d.hexdigest()

def exposure_fingerprint(frame):
    d=hashlib.sha256()
    for r in frame.sort_values("physical_segment_id").itertuples(index=False,name=None): d.update(("|".join(map(str,r))+"\n").encode())
    return d.hexdigest()

def match(accidents,candidates,exposure,threshold=PRIMARY_THRESHOLD_M):
    if threshold<=0: raise SpatialContractError("threshold must be positive")
    if set(accidents.reconstructed_accident_id)!=set(candidates.reconstructed_accident_id): raise SpatialContractError("accident/candidate ID set mismatch")
    cand=candidates.set_index("reconstructed_accident_id"); exp=exposure.set_index("physical_segment_id")
    if not exp.index.is_unique: raise SpatialContractError("duplicate physical segment exposure key")
    rows=[]
    for a in accidents.sort_values("reconstructed_accident_id").itertuples(index=False):
        c=cand.loc[a.reconstructed_accident_id]; status,basis,key,diag=classify(c,threshold); d1,d2,gap,ties,constrained=diag
        assigned=parse_key(key) if key else (None,None,None,None); e=exp.loc[key] if key else None
        if key and (key not in exp.index or int(e.bidirectional_total_trip_weight)<=0): raise SpatialContractError("assigned segment exposure join failed")
        rows.append({"reconstructed_accident_id":a.reconstructed_accident_id,"year":int(a.year),"event_datetime":a.event_datetime,"road_context_status":a.road_context_status,"match_status":status,"match_basis":basis,
          "assigned_endpoint1_lon_e6":assigned[0],"assigned_endpoint1_lat_e6":assigned[1],"assigned_endpoint2_lon_e6":assigned[2],"assigned_endpoint2_lat_e6":assigned[3],"assigned_physical_segment_id":key,
          "nearest_distance_m":d1,"second_nearest_distance_m":d2,"distance_gap_m":gap,"minimum_distance_candidate_count":ties,"road_context_constrained":constrained,
          "directional_member_count":None if e is None else int(e.directional_member_count),"bidirectional_total_trip_weight":None if e is None else int(e.bidirectional_total_trip_weight),"bidirectional_weekday_trip_weight":None if e is None else int(e.bidirectional_weekday_trip_weight),"bidirectional_holiday_trip_weight":None if e is None else int(e.bidirectional_holiday_trip_weight),
          "source_accident_context_fingerprint":EXPECTED_ACCIDENT_FP,"source_candidate_validation_fingerprint":EXPECTED_CANDIDATE_FP,"source_direction_neutral_fingerprint":EXPECTED_NEUTRAL_FP})
    out=pd.DataFrame(rows,columns=MATCH_COLUMNS)
    nullable_integer_columns=["assigned_endpoint1_lon_e6","assigned_endpoint1_lat_e6","assigned_endpoint2_lon_e6","assigned_endpoint2_lat_e6","minimum_distance_candidate_count","directional_member_count","bidirectional_total_trip_weight","bidirectional_weekday_trip_weight","bidirectional_holiday_trip_weight"]
    for column in nullable_integer_columns: out[column]=out[column].astype("Int64")
    matched=out.match_status.isin(["matched_context","matched_global"]); assigned=out.assigned_physical_segment_id.notna()
    if not matched.equals(assigned): raise SpatialContractError("assignment null policy failed")
    expcols=[c for c in out if c.startswith("bidirectional_") or c=="directional_member_count"]
    if out.loc[~matched,expcols].notna().any().any() or out.loc[matched,expcols].isna().any().any(): raise SpatialContractError("exposure null policy failed")
    if len(out)!=len(accidents) or not out.reconstructed_accident_id.is_unique: raise SpatialContractError("row/ID conservation failed")
    return out

def sensitivity(candidates,thresholds=(5.0,10.0,20.0)):
    result={}
    for t in thresholds:
        counts=Counter(classify(r,t)[0] for r in candidates.itertuples(index=False))
        result[f"{t:g}m"]={k:int(counts.get(k,0)) for k in ["matched_context","matched_global","context_no_brouter_candidate","unmatched_distance","ambiguous_exact_tie","coordinate_unavailable","contained_multiple_unresolved"]}
    return result

def quality_summary(matches):
    groups={"all":matches,**{k:v for k,v in matches.groupby("road_context_status",sort=True)}}; out={}
    for name,g in groups.items():
        n=len(g); matched=int(g.match_status.isin(["matched_context","matched_global"]).sum()); amb=int((g.match_status=="ambiguous_exact_tie").sum()); dist=int((g.match_status=="unmatched_distance").sum()); no=int((g.match_status=="context_no_brouter_candidate").sum())
        out[name]={"count":n,"matched":matched,"matched_pct":matched/n,"ambiguous":amb,"ambiguous_pct":amb/n,"unmatched_distance":dist,"unmatched_distance_pct":dist/n,"no_candidate":no,"no_candidate_pct":no/n}
    return out

def load_inputs(root):
    p4=json.loads((root/"notes/phase8_4a-accident-brouter-candidate-validation.json").read_text(encoding="utf8")); p3=json.loads((root/"notes/phase8_3c-accident-road-context.json").read_text(encoding="utf8")); p2=json.loads((root/"notes/phase8_2-segment-usage-completion.json").read_text(encoding="utf8"))
    dp=root/DIRECTED_PATH; ap=root/ACCIDENT_PATH; np=root/p4["outputs"]["neutral_path"]; cp=root/p4["outputs"]["validation_path"]
    for path,expected in [(dp,EXPECTED_DIRECTED_SHA),(ap,EXPECTED_ACCIDENT_SHA),(np,EXPECTED_NEUTRAL_SHA),(cp,EXPECTED_CANDIDATE_SHA)]:
        if sha256_file(path)!=expected: raise SpatialContractError(f"locked SHA mismatch: {path}")
    directed=pd.read_parquet(dp); accidents=pd.read_parquet(ap); neutral=pd.read_parquet(np); candidates=pd.read_parquet(cp)
    if len(directed)!=149234 or directed_fingerprint(directed)!=EXPECTED_DIRECTED_FP: raise SpatialContractError("Phase 8.2 identity mismatch")
    if len(accidents)!=46586 or final_output_fingerprint(accidents)!=EXPECTED_ACCIDENT_FP: raise SpatialContractError("Phase 8.3C identity mismatch")
    if len(neutral)!=106049 or neutral_fingerprint(neutral)!=EXPECTED_NEUTRAL_FP: raise SpatialContractError("neutral artifact identity mismatch")
    if len(candidates)!=46586 or candidate_fingerprint(candidates)!=EXPECTED_CANDIDATE_FP: raise SpatialContractError("candidate artifact identity mismatch")
    return directed,accidents,neutral,candidates,p2,p3,p4

def execute(root,exposure_path,match_path,receipt_path):
    directed,accidents,neutral,candidates,p2,p3,p4=load_inputs(root); exposure,totals=build_exposure(directed)
    if set(exposure.physical_segment_id)!=set(neutral.physical_segment_key): raise SpatialContractError("exposure/neutral segment set mismatch")
    matches=match(accidents,candidates,exposure); statuses=matches.match_status.value_counts().to_dict()
    if sum(statuses.values())!=46586: raise SpatialContractError("status conservation failed")
    atomic_parquet(exposure_path,exposure); atomic_parquet(match_path,matches)
    sens=sensitivity(candidates); matched=matches[matches.match_status.isin(["matched_context","matched_global"])]
    near={str(x):int((matched.distance_gap_m<=x).sum()) for x in (.1,.5,1.0)}
    receipt={"contract_version":CONTRACT_VERSION,"generated_at_utc":datetime.now(timezone.utc).isoformat(timespec="seconds"),"locked_inputs":{"phase8_2_fingerprint":EXPECTED_DIRECTED_FP,"phase8_2_sha256":EXPECTED_DIRECTED_SHA,"phase8_3c_fingerprint":EXPECTED_ACCIDENT_FP,"phase8_3c_sha256":EXPECTED_ACCIDENT_SHA,"phase8_4a_candidate_fingerprint":EXPECTED_CANDIDATE_FP,"phase8_4a_candidate_sha256":EXPECTED_CANDIDATE_SHA,"direction_neutral_fingerprint":EXPECTED_NEUTRAL_FP,"direction_neutral_sha256":EXPECTED_NEUTRAL_SHA},
      "policy":{"primary_threshold_m":10.0,"sensitivity_thresholds_m":[5,20],"road_context_policy":"constrained candidate space required when polygon context exists; no global fallback when empty","outside_reference_policy":"global direction-neutral candidate space","exact_tie_policy":"ambiguous when within threshold; no winner","near_tie_policy":"retained diagnostic; unique nearest remains eligible","flow_used_for_matching":False},
      "population":{"accident_count":len(matches),"status_counts":{k:int(v) for k,v in sorted(statuses.items())},"overall_primary_match_rate":float(matches.match_status.isin(["matched_context","matched_global"]).mean()),"quality_by_road_context":quality_summary(matches)},
      "sensitivity":sens,"primary_matched_near_ties":near,
      "exposure":{"row_count":len(exposure),"one_direction_only_rows":int((exposure.directional_member_count==1).sum()),"both_directions_rows":int((exposure.directional_member_count==2).sum()),"total":totals[0],"weekday":totals[1],"holiday":totals[2],"day_type_conservation":totals[0]==totals[1]+totals[2],"fingerprint_sha256":exposure_fingerprint(exposure),"path":exposure_path.relative_to(root).as_posix(),"parquet_sha256":sha256_file(exposure_path)},
      "output":{"path":match_path.relative_to(root).as_posix(),"rows":len(matches),"fingerprint_sha256":matching_fingerprint(matches),"parquet_sha256":sha256_file(match_path),"sorted_by":"reconstructed_accident_id"},
      "validation":{"id_set_equal":set(matches.reconstructed_accident_id)==set(accidents.reconstructed_accident_id),"assigned_segment_fk_valid":set(matched.assigned_physical_segment_id).issubset(set(exposure.physical_segment_id)),"exposure_join_exactly_one":True,"status_conservation":True,"null_policy":True},
      "prohibited_work_confirmed_not_performed":{"epdo":False,"cbi":False,"accidents_divided_by_exposure":False,"risk_score":False,"hotspot_ranking":False},"readiness":{"phase8_5":"READY_FOR_SEPARATELY_AUTHORIZED_RISK_CONTRACT"}}
    receipt["receipt_fingerprint_sha256"]=stable_receipt_fingerprint(receipt); atomic_json(receipt_path,receipt); return receipt

def main():
    root=Path(__file__).resolve().parents[1]; p=argparse.ArgumentParser(); p.add_argument("--root",type=Path,default=root); a=p.parse_args(); r=execute(a.root.resolve(),a.root/EXPOSURE_PATH,a.root/MATCH_PATH,a.root/"notes/phase8_4b-accident-brouter-matching.json"); print(json.dumps({"status_counts":r["population"]["status_counts"],"match_rate":r["population"]["overall_primary_match_rate"]},ensure_ascii=False))
if __name__=="__main__": main()
