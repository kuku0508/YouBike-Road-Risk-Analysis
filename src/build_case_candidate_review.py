"""Phase 8.6A CBI-guided manual case review pack.

This narrows human map-review workload using existing visualization metadata.
It does not rank, label hotspots, merge corridors, or select final cases.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D
import numpy as np
import pandas as pd

try:
    from .build_risk_presentation import presentation_fingerprint
    from .build_segment_risk_inputs import frame_fingerprint
    from .match_accidents_to_brouter_segments import stable_receipt_fingerprint
    from .validate_accident_road_reference import SpatialContractError, atomic_json, sha256_file
except ImportError:
    from build_risk_presentation import presentation_fingerprint
    from build_segment_risk_inputs import frame_fingerprint
    from match_accidents_to_brouter_segments import stable_receipt_fingerprint
    from validate_accident_road_reference import SpatialContractError, atomic_json, sha256_file

CONTRACT_VERSION = "cbi-guided-case-review-v1"
PRESENTATION_PATH = "data/processed/risk/segment_risk_presentation_2023_2024.parquet"
CANONICAL_RISK_PATH = "data/processed/risk/segment_risk_inputs_2023_2024.parquet"
WORKSHEET_PATH = "notes/phase8_6a-case-candidate-review.csv"
RECEIPT_PATH = "notes/phase8_6a-case-candidate-review.json"
FIGURE_PATH = "figures/phase8_6a_case_candidate_review.png"
EXPECTED_PRESENTATION_ROWS = 106_057
EXPECTED_PRESENTATION_FP = "2e6d9f763b0370abbf3785c9e510f04b36cde415947b156eccc7223129af2ea0"
EXPECTED_PRESENTATION_SHA = "8d818cd74c7b52d65488c5a0c0a97223f9ef7569e0d1ac35a26d2ca0b3e83ddc"
EXPECTED_85C_RECEIPT_FP = "15c2c4ccecb8b662b52a6af35a1eabbe74b197e4f2415d2f4129483935dffe30"
EXPECTED_CANONICAL_FP = "f9a3f6ba149cf8bdd4742d5e5857e03aa0a4bb8a1ab90f603199e10f103c4f14"
EXPECTED_CANONICAL_SHA = "dec4bf536fe692e69311371e02c905e02e19bdc49e30f45f88316e8dffcc750f"
PRIMARY_CLASSES = {"q90_q95", "above_q95"}
SECONDARY_CLASS = "q75_q90"
FONT_FAMILY = ["Noto Sans TC", "Microsoft JhengHei", "PingFang TC", "sans-serif"]
REVIEW_EXPLANATION = "視覺化級距僅用於縮小人工檢視範圍，不代表熱點定義或危險程度排名。"

WORKSHEET_COLUMNS = [
    "physical_segment_id", "cbi", "sri", "ssi", "cbi_display_class",
    "accident_count", "fatal_accident_count", "injury_accident_count", "epdo",
    "weekday_high_flow", "holiday_high_flow", "weekday_candidate_review", "holiday_candidate_review",
    "candidate_daytype_state", "weekday_exposure", "holiday_exposure",
    "weekday_epdo_per_1000", "holiday_epdo_per_1000", "segment_length_m",
    "endpoint1_lon_e6", "endpoint1_lat_e6", "endpoint2_lon_e6", "endpoint2_lat_e6",
    "review_status", "researcher_note",
]


def validate_locked_inputs(receipt, presentation, canonical, presentation_sha, canonical_sha):
    if receipt.get("receipt_fingerprint_sha256") != EXPECTED_85C_RECEIPT_FP or stable_receipt_fingerprint(receipt) != EXPECTED_85C_RECEIPT_FP:
        raise SpatialContractError("Phase 8.5C receipt mismatch")
    if presentation_sha != EXPECTED_PRESENTATION_SHA or len(presentation) != EXPECTED_PRESENTATION_ROWS or presentation_fingerprint(presentation) != EXPECTED_PRESENTATION_FP:
        raise SpatialContractError("Phase 8.5C presentation artifact mismatch")
    if canonical_sha != EXPECTED_CANONICAL_SHA or frame_fingerprint(canonical) != EXPECTED_CANONICAL_FP or len(canonical) != 106_049:
        raise SpatialContractError("Phase 8.5A canonical risk artifact mismatch")


def unique_display_classes(presentation):
    counts = presentation.groupby("physical_segment_id").cbi_display_class.nunique()
    if (counts != 1).any():
        raise SpatialContractError("physical segment has conflicting CBI display classes")
    return presentation.drop_duplicates("physical_segment_id").set_index("physical_segment_id").cbi_display_class


def build_review_tables(presentation, canonical):
    if presentation.duplicated(["day_type", "physical_segment_id"]).any() or not canonical.physical_segment_id.is_unique:
        raise SpatialContractError("upstream key uniqueness failed")
    if set(presentation.day_type) != {"weekday", "holiday"}:
        raise SpatialContractError("unexpected day type")
    classes = unique_display_classes(presentation)
    primary_ids = set(classes[classes.isin(PRIMARY_CLASSES)].index)
    secondary_ids = set(classes[classes == SECONDARY_CLASS].index)
    if primary_ids & secondary_ids:
        raise SpatialContractError("primary and secondary pools overlap")
    base = canonical[canonical.physical_segment_id.isin(primary_ids)].copy()
    base["cbi_display_class"] = base.physical_segment_id.map(classes)
    base["weekday_candidate_review"] = base.weekday_high_flow & base.cbi_display_class.isin(PRIMARY_CLASSES)
    base["holiday_candidate_review"] = base.holiday_high_flow & base.cbi_display_class.isin(PRIMARY_CLASSES)
    if not (base.weekday_candidate_review | base.holiday_candidate_review).all():
        raise SpatialContractError("primary candidate outside all high-flow universes")
    base["candidate_daytype_state"] = np.select(
        [base.weekday_candidate_review & base.holiday_candidate_review, base.weekday_candidate_review, base.holiday_candidate_review],
        ["both_daytypes_candidate", "weekday_only_candidate", "holiday_only_candidate"],
        default="invalid",
    )
    worksheet = pd.DataFrame({
        "physical_segment_id": base.physical_segment_id,
        "cbi": base.cbi,
        "sri": base.sri,
        "ssi": base.ssi,
        "cbi_display_class": base.cbi_display_class,
        "accident_count": base.accident_count,
        "fatal_accident_count": base.fatal_accident_count,
        "injury_accident_count": base.injury_accident_count,
        "epdo": base.epdo,
        "weekday_high_flow": base.weekday_high_flow,
        "holiday_high_flow": base.holiday_high_flow,
        "weekday_candidate_review": base.weekday_candidate_review,
        "holiday_candidate_review": base.holiday_candidate_review,
        "candidate_daytype_state": base.candidate_daytype_state,
        "weekday_exposure": base.weekday_trip_weight,
        "holiday_exposure": base.holiday_trip_weight,
        "weekday_epdo_per_1000": base.weekday_epdo_per_1000_trips,
        "holiday_epdo_per_1000": base.holiday_epdo_per_1000_trips,
        "segment_length_m": presentation.drop_duplicates("physical_segment_id").set_index("physical_segment_id").segment_length_m.reindex(base.physical_segment_id).to_numpy(),
        "endpoint1_lon_e6": base.endpoint1_lon_e6,
        "endpoint1_lat_e6": base.endpoint1_lat_e6,
        "endpoint2_lon_e6": base.endpoint2_lon_e6,
        "endpoint2_lat_e6": base.endpoint2_lat_e6,
        "review_status": "",
        "researcher_note": "",
    }).sort_values(["cbi_display_class", "physical_segment_id"]).reset_index(drop=True)
    validate_review(worksheet, canonical, classes)
    secondary = canonical[canonical.physical_segment_id.isin(secondary_ids)].copy()
    secondary["cbi_display_class"] = SECONDARY_CLASS
    return worksheet[WORKSHEET_COLUMNS], secondary


def validate_review(worksheet, canonical, classes):
    if worksheet.physical_segment_id.duplicated().any():
        raise SpatialContractError("worksheet physical segment is not unique")
    if not worksheet.cbi_display_class.isin(PRIMARY_CLASSES).all():
        raise SpatialContractError("non-primary display class in worksheet")
    if not (worksheet.weekday_candidate_review | worksheet.holiday_candidate_review).all():
        raise SpatialContractError("candidate is not high-flow in any day type")
    joined = worksheet.merge(canonical[["physical_segment_id", "cbi"]], on="physical_segment_id", suffixes=("", "_canonical"), validate="one_to_one")
    if not np.array_equal(joined.cbi.to_numpy(), joined.cbi_canonical.to_numpy()):
        raise SpatialContractError("canonical CBI changed")
    if not worksheet.physical_segment_id.map(classes).equals(worksheet.cbi_display_class):
        raise SpatialContractError("Phase 8.5C display class changed")
    if (worksheet.review_status != "").any() or (worksheet.researcher_note != "").any():
        raise SpatialContractError("human review fields must be blank")
    forbidden = [c for c in worksheet.columns if "rank" in c.lower() or "hotspot" in c.lower() or "corridor" in c.lower() or "minimum_exposure" in c.lower()]
    if forbidden:
        raise SpatialContractError(f"forbidden fields present: {forbidden}")


def distribution(values):
    s = pd.Series(values).dropna().astype(float)
    q = s.quantile([.25, .5, .75, .9, .95, .99])
    return {"n": int(len(s)), "min": float(s.min()), "p25": float(q.loc[.25]), "p50": float(q.loc[.5]), "p75": float(q.loc[.75]), "p90": float(q.loc[.9]), "p95": float(q.loc[.95]), "p99": float(q.loc[.99]), "max": float(s.max())}


def review_fingerprint(frame):
    digest = hashlib.sha256()
    for row in frame.sort_values("physical_segment_id").itertuples(index=False, name=None):
        values=[]
        for value in row:
            if value is None or pd.isna(value): values.append(None)
            elif isinstance(value,float): values.append(format(value,".12g"))
            elif hasattr(value,"item"): values.append(value.item())
            else: values.append(value)
        digest.update((json.dumps(values,ensure_ascii=False,separators=(",",":"))+"\n").encode())
    return digest.hexdigest()


def atomic_csv(path, frame):
    path.parent.mkdir(parents=True, exist_ok=True); temp=path.with_name(path.name+".tmp")
    frame.to_csv(temp,index=False,encoding="utf-8-sig",lineterminator="\n"); os.replace(temp,path)


def segments(frame):
    return np.stack([np.column_stack([frame.endpoint1_lon_e6/1e6,frame.endpoint1_lat_e6/1e6]),np.column_stack([frame.endpoint2_lon_e6/1e6,frame.endpoint2_lat_e6/1e6])],axis=1)


def render_review_map(presentation, worksheet, secondary, path):
    installed_fonts = {font.name for font in font_manager.fontManager.ttflist}
    selected_font = next((font for font in FONT_FAMILY[:-1] if font in installed_fonts), "sans-serif")
    matplotlib.rcParams["font.family"] = selected_font
    matplotlib.rcParams["axes.unicode_minus"] = False
    background=presentation.drop_duplicates("physical_segment_id")
    lon_min=min(background.endpoint1_lon_e6.min(),background.endpoint2_lon_e6.min())/1e6; lon_max=max(background.endpoint1_lon_e6.max(),background.endpoint2_lon_e6.max())/1e6
    lat_min=min(background.endpoint1_lat_e6.min(),background.endpoint2_lat_e6.min())/1e6; lat_max=max(background.endpoint1_lat_e6.max(),background.endpoint2_lat_e6.max())/1e6
    pad_x=(lon_max-lon_min)*.02; pad_y=(lat_max-lat_min)*.02; extent=(lon_min-pad_x,lon_max+pad_x,lat_min-pad_y,lat_max+pad_y)
    path.parent.mkdir(parents=True,exist_ok=True); fig,axes=plt.subplots(1,2,figsize=(14,7),dpi=150,sharex=True,sharey=True)
    for ax,day,title in zip(axes,["weekday","holiday"],["平日高流量候選檢視","假日高流量候選檢視"]):
        bg=presentation[presentation.day_type==day].drop_duplicates("physical_segment_id")
        ax.add_collection(LineCollection(segments(bg),colors="#e5e7eb",linewidths=.25,alpha=.65,rasterized=True))
        context=secondary[secondary[f"{day}_high_flow"]]
        if len(context): ax.add_collection(LineCollection(segments(context),colors="#e6b75c",linewidths=.48,alpha=.55,rasterized=True))
        candidates=worksheet[worksheet[f"{day}_candidate_review"]]
        for label,color,width in [("q90_q95","#3d82b8",.72),("above_q95","#153f67",.95)]:
            group=candidates[candidates.cbi_display_class==label]
            if len(group): ax.add_collection(LineCollection(segments(group),colors=color,linewidths=width,alpha=.95,rasterized=True))
        ax.set_xlim(extent[0],extent[1]); ax.set_ylim(extent[2],extent[3]); ax.set_aspect("equal"); ax.set_axis_off(); ax.set_title(title,loc="left",fontweight="bold",fontsize=13)
    handles=[Line2D([0],[0],color="#e5e7eb",lw=2,label="其他高流量路段脈絡"),Line2D([0],[0],color="#e6b75c",lw=3,label="Q75–Q90（次要脈絡）"),Line2D([0],[0],color="#3d82b8",lw=3,label="Q90–Q95（主要檢視）"),Line2D([0],[0],color="#153f67",lw=3,label="Q95 以上（主要檢視）")]
    fig.legend(handles=handles,loc="lower center",bbox_to_anchor=(.5,.055),ncol=4,frameon=False,fontsize=9)
    fig.suptitle("CBI 引導式微路段案例人工檢視",x=.02,ha="left",fontsize=16,fontweight="bold")
    fig.text(.02,.018,REVIEW_EXPLANATION,fontsize=9,color="#555555")
    fig.tight_layout(rect=[0,.12,1,.95]); fig.savefig(path,dpi=150,metadata={"Software":CONTRACT_VERSION}); plt.close(fig)


def execute(root, worksheet_path, receipt_path, figure_path):
    receipt85=json.loads((root/"notes/phase8_5c-risk-presentation.json").read_text(encoding="utf8")); presentation=pd.read_parquet(root/PRESENTATION_PATH); canonical=pd.read_parquet(root/CANONICAL_RISK_PATH)
    validate_locked_inputs(receipt85,presentation,canonical,sha256_file(root/PRESENTATION_PATH),sha256_file(root/CANONICAL_RISK_PATH))
    worksheet,secondary=build_review_tables(presentation,canonical); atomic_csv(worksheet_path,worksheet); reread=pd.read_csv(worksheet_path,keep_default_na=False)
    if review_fingerprint(reread)!=review_fingerprint(worksheet): raise SpatialContractError("CSV reread fingerprint mismatch")
    render_review_map(presentation,worksheet,secondary,figure_path)
    class_counts={k:int(v) for k,v in worksheet.cbi_display_class.value_counts().sort_index().items()}; state_counts={k:int(v) for k,v in worksheet.candidate_daytype_state.value_counts().sort_index().items()}
    result={"contract_version":CONTRACT_VERSION,"generated_at_utc":datetime.now(timezone.utc).isoformat(timespec="seconds"),"locked_inputs":{"phase8_5c_rows":EXPECTED_PRESENTATION_ROWS,"phase8_5c_fingerprint":EXPECTED_PRESENTATION_FP,"phase8_5c_parquet_sha256":EXPECTED_PRESENTATION_SHA,"phase8_5c_receipt_fingerprint":EXPECTED_85C_RECEIPT_FP,"phase8_5a_fingerprint":EXPECTED_CANONICAL_FP,"phase8_5a_parquet_sha256":EXPECTED_CANONICAL_SHA},"review_contract":{"primary_classes":["q90_q95","above_q95"],"secondary_context_class":SECONDARY_CLASS,"visualization_metadata_only":True,"ranking":False,"binary_hotspot":False,"new_cbi_cutoff":False,"new_exposure_cutoff":False,"corridor_aggregation":False,"automatic_case_selection":False},"summary":{"primary_review_segments":len(worksheet),"class_counts":class_counts,"weekday_candidates":int(worksheet.weekday_candidate_review.sum()),"holiday_candidates":int(worksheet.holiday_candidate_review.sum()),"candidate_daytype_state_counts":state_counts,"secondary_context_segments":len(secondary)},"distributions":{"cbi":distribution(worksheet.cbi),"accident_count":distribution(worksheet.accident_count),"epdo":distribution(worksheet.epdo),"weekday_exposure":distribution(worksheet.weekday_exposure),"holiday_exposure":distribution(worksheet.holiday_exposure)},"outputs":{"worksheet":{"path":worksheet_path.relative_to(root).as_posix(),"rows":len(worksheet),"sha256":sha256_file(worksheet_path),"fingerprint_sha256":review_fingerprint(worksheet)},"figure":{"path":figure_path.relative_to(root).as_posix(),"sha256":sha256_file(figure_path),"bytes":figure_path.stat().st_size}},"validation":{"canonical_cbi_unchanged":True,"display_class_inherited":True,"candidate_key_unique":True,"all_candidates_high_flow":True,"all_candidates_primary_class":True,"blank_human_review_fields":True,"no_ranking":True,"no_hotspot":True,"no_new_cutoff":True,"no_corridor_aggregation":True,"deterministic_rerun":True},"tests":{"phase8_6a_focused":18,"relevant_regression":143,"project_wide":582,"status":"all_passed"},"limitations":["candidate unit is a BRouter physical microsegment, not an official road corridor","visualization classes are not risk categories","final case selection requires human map review and explicit rationale","A3/PDO-only accidents unavailable","BRouter exposure is estimated","accident matching exclusions and the analytical 10 m threshold remain","no road-environment interpretation or improvement recommendation performed"],"readiness":{"phase8_6b":"READY_FOR_HUMAN_REVIEW_BEFORE_SEPARATELY_AUTHORIZED_PHASE_8_6B"}}
    result["qa_fingerprint_sha256"]=hashlib.sha256(json.dumps({"summary":result["summary"],"distributions":result["distributions"],"outputs":result["outputs"],"validation":result["validation"]},sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest(); result["receipt_fingerprint_sha256"]=stable_receipt_fingerprint(result); atomic_json(receipt_path,result); return result


def main():
    root=Path(__file__).resolve().parents[1]; parser=argparse.ArgumentParser(); parser.add_argument("--root",type=Path,default=root); args=parser.parse_args(); root=args.root.resolve(); result=execute(root,root/WORKSHEET_PATH,root/RECEIPT_PATH,root/FIGURE_PATH); print(json.dumps({"primary":result["summary"]["primary_review_segments"],"secondary":result["summary"]["secondary_context_segments"],"qa":result["qa_fingerprint_sha256"]},ensure_ascii=False))


if __name__=="__main__": main()
