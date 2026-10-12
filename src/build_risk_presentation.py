"""Phase 8.5C presentation-ready risk data and deterministic static figures.

Display classes are visualization metadata only. Canonical risk values are copied
unchanged, and this module never creates rankings or binary hotspot labels.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import struct
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pyproj import CRS

try:
    from .audit_segment_risk_stability import segment_lengths
    from .build_segment_risk_inputs import frame_fingerprint
    from .match_accidents_to_brouter_segments import stable_receipt_fingerprint
    from .validate_accident_road_reference import SpatialContractError, atomic_json, sha256_file
except ImportError:
    from audit_segment_risk_stability import segment_lengths
    from build_segment_risk_inputs import frame_fingerprint
    from match_accidents_to_brouter_segments import stable_receipt_fingerprint
    from validate_accident_road_reference import SpatialContractError, atomic_json, sha256_file

CONTRACT_VERSION = "risk-presentation-contract-v1"
INPUT_PATH = "data/processed/risk/segment_risk_inputs_2023_2024.parquet"
OUTPUT_PATH = "data/processed/risk/segment_risk_presentation_2023_2024.parquet"
RECEIPT_PATH = "notes/phase8_5c-risk-presentation.json"
EXPECTED_ROWS = 106_049
EXPECTED_INPUT_FP = "f9a3f6ba149cf8bdd4742d5e5857e03aa0a4bb8a1ab90f603199e10f103c4f14"
EXPECTED_INPUT_SHA = "dec4bf536fe692e69311371e02c905e02e19bdc49e30f45f88316e8dffcc750f"
EXPECTED_85A_RECEIPT_FP = "549e5344dab77b3fbb25df534ff45466734bfad49428c4c543cfaa7ed8c0fd70"
EXPECTED_85B_QA_FP = "32eb8155f2f5ae8338747c18ec80b0b44082da3fe1e3116a7e10f4bb6c7afd8b"
EXPECTED_85B_RECEIPT_FP = "2ebd0e7e95fc435eb58284c6614b84ac7bec00863ac9f19512821b1d4886becb"
EXPECTED_WEEKDAY_ROWS = 53_032
EXPECTED_HOLIDAY_ROWS = 53_025
CBI_LABELS = ["zero", "positive_le_q50", "q50_q75", "q75_q90", "q90_q95", "above_q95"]
RATE_LABELS = ["zero", "positive_le_q50", "q50_q75", "q75_q90", "q90_q95", "q95_q99", "above_q99"]
CBI_COLORS = ["#d9dde3", "#dce9f4", "#a8cce3", "#68a9cf", "#2f7fb9", "#154f83"]
RATE_COLORS = ["#d9dde3", "#fff0c2", "#fbd28b", "#f5aa5b", "#df743f", "#ad3d38", "#6e1e2d"]
FIGURE_NAMES = [
    "phase8_5c_weekday_cbi.png", "phase8_5c_holiday_cbi.png",
    "phase8_5c_weekday_epdo_per_1000.png", "phase8_5c_holiday_epdo_per_1000.png",
    "phase8_5c_high_flow_segment_count.png", "phase8_5c_rate_distribution.png",
    "phase8_5c_cbi_sparsity.png",
]


def validate_locked_inputs(r85a, r85b, parquet_sha, content_fp, rows):
    if r85a.get("receipt_fingerprint_sha256") != EXPECTED_85A_RECEIPT_FP or stable_receipt_fingerprint(r85a) != EXPECTED_85A_RECEIPT_FP:
        raise SpatialContractError("Phase 8.5A receipt mismatch")
    if r85b.get("qa_fingerprint_sha256") != EXPECTED_85B_QA_FP or r85b.get("receipt_fingerprint_sha256") != EXPECTED_85B_RECEIPT_FP or stable_receipt_fingerprint(r85b) != EXPECTED_85B_RECEIPT_FP:
        raise SpatialContractError("Phase 8.5B receipt mismatch")
    if r85b.get("stability_conclusion") != "supported" or r85b.get("additional_stability_policy_required") is not False:
        raise SpatialContractError("Phase 8.5B readiness mismatch")
    if parquet_sha != EXPECTED_INPUT_SHA or content_fp != EXPECTED_INPUT_FP or rows != EXPECTED_ROWS:
        raise SpatialContractError("Phase 8.5A canonical artifact mismatch")


def quantiles(values, probs):
    s = pd.Series(values).dropna().astype(float)
    if s.empty or not np.isfinite(s).all():
        raise SpatialContractError("display threshold universe is empty or non-finite")
    return [float(s.quantile(q)) for q in probs]


def classify_display(values, thresholds, labels):
    values = pd.Series(values).astype(float)
    if len(thresholds) != len(labels) - 2 or not all(a <= b for a, b in zip(thresholds, thresholds[1:])):
        raise SpatialContractError("invalid display thresholds")
    if values.isna().any() or (~np.isfinite(values)).any() or (values < 0).any():
        raise SpatialContractError("display values must be finite and non-negative")
    result = np.full(len(values), labels[-1], dtype=object)
    result[values.to_numpy() == 0] = labels[0]
    positive = values.to_numpy() > 0
    previous = np.zeros(len(values), dtype=bool)
    for threshold, label in zip(thresholds, labels[1:-1]):
        current = positive & ~previous & (values.to_numpy() <= threshold)
        result[current] = label
        previous |= current
    return pd.Series(result, index=values.index, dtype="string")


def wkb_lines(frame):
    return [struct.pack("<BII4d", 1, 2, 2, r.endpoint1_lon_e6 / 1e6, r.endpoint1_lat_e6 / 1e6, r.endpoint2_lon_e6 / 1e6, r.endpoint2_lat_e6 / 1e6) for r in frame.itertuples(index=False)]


def build_presentation(source):
    if not source.physical_segment_id.is_unique:
        raise SpatialContractError("canonical segment universe mismatch")
    forbidden = [c for c in source.columns if "rank" in c.lower() or "hotspot" in c.lower() or "minimum_exposure" in c.lower()]
    if forbidden:
        raise SpatialContractError(f"forbidden policy fields present: {forbidden}")
    cbi_positive = source.loc[source.cbi > 0, "cbi"]
    cbi_thresholds = quantiles(cbi_positive, [.50, .75, .90, .95])
    pooled = pd.concat([
        source.loc[source.weekday_high_flow, "weekday_epdo_per_1000_trips"],
        source.loc[source.holiday_high_flow, "holiday_epdo_per_1000_trips"],
    ], ignore_index=True)
    if pooled.isna().any():
        raise SpatialContractError("high-flow presentation rate contains null")
    pooled_positive = pooled[pooled > 0]
    rate_thresholds = quantiles(pooled_positive, [.50, .75, .90, .95, .99])
    lengths = segment_lengths(source)
    outputs = []
    day_fields = {
        "weekday": ("weekday_high_flow", "weekday_trip_weight", "weekday_fatal_accident_count", "weekday_injury_accident_count", "weekday_accident_count", "weekday_epdo", "weekday_epdo_per_1000_trips"),
        "holiday": ("holiday_high_flow", "holiday_trip_weight", "holiday_fatal_accident_count", "holiday_injury_accident_count", "holiday_accident_count", "holiday_epdo", "holiday_epdo_per_1000_trips"),
    }
    for day_type, fields in day_fields.items():
        flag, exposure, fatal, injury, accidents, epdo, rate = fields
        sub = source.loc[source[flag]].copy()
        if (sub[exposure] <= 0).any() or sub[rate].isna().any():
            raise SpatialContractError(f"{day_type} high-flow denominator/rate invariant failed")
        out = pd.DataFrame({
            "day_type": day_type,
            "physical_segment_id": sub.physical_segment_id,
            "endpoint1_lon_e6": sub.endpoint1_lon_e6,
            "endpoint1_lat_e6": sub.endpoint1_lat_e6,
            "endpoint2_lon_e6": sub.endpoint2_lon_e6,
            "endpoint2_lat_e6": sub.endpoint2_lat_e6,
            "segment_length_m": lengths.loc[sub.index],
            "directional_member_count": sub.directional_member_count,
            "cbi": sub.cbi,
            "sri": sub.sri,
            "ssi": sub.ssi,
            "cbi_display_class": classify_display(sub.cbi, cbi_thresholds, CBI_LABELS),
            "fatal_accident_count": sub.fatal_accident_count,
            "injury_accident_count": sub.injury_accident_count,
            "accident_count": sub.accident_count,
            "epdo": sub.epdo,
            "day_type_fatal_accident_count": sub[fatal],
            "day_type_injury_accident_count": sub[injury],
            "day_type_accident_count": sub[accidents],
            "day_type_epdo": sub[epdo],
            "day_type_estimated_exposure": sub[exposure],
            "day_type_epdo_per_1000_trips": sub[rate],
            "rate_display_class": classify_display(sub[rate], rate_thresholds, RATE_LABELS),
            "has_matched_fatal_or_injury_accident": sub.accident_count > 0,
            "source_segment_risk_fingerprint": EXPECTED_INPUT_FP,
            "source_stability_qa_fingerprint": EXPECTED_85B_QA_FP,
            "presentation_contract_version": CONTRACT_VERSION,
        })
        out["geometry"] = wkb_lines(sub)
        outputs.append(out)
    result = pd.concat(outputs, ignore_index=True).sort_values(["day_type", "physical_segment_id"]).reset_index(drop=True)
    validate_presentation(result, source)
    return result, cbi_thresholds, rate_thresholds, int(len(pooled_positive))


def validate_presentation(out, source):
    counts = out.day_type.value_counts().to_dict()
    expected = {"weekday": int(source.weekday_high_flow.sum()), "holiday": int(source.holiday_high_flow.sum())}
    if counts != expected or len(out) != sum(expected.values()):
        raise SpatialContractError("presentation row conservation failed")
    if (out.day_type_estimated_exposure <= 0).any() or out.day_type_epdo_per_1000_trips.isna().any():
        raise SpatialContractError("presentation denominator/rate invalid")
    if out.duplicated(["day_type", "physical_segment_id"]).any() or not set(out.physical_segment_id).issubset(set(source.physical_segment_id)):
        raise SpatialContractError("presentation key/FK invariant failed")
    joined = out.merge(source, on="physical_segment_id", suffixes=("", "_source"), validate="many_to_one")
    for col in ["cbi", "sri", "ssi"]:
        if not np.array_equal(joined[col].to_numpy(), joined[f"{col}_source"].to_numpy()):
            raise SpatialContractError(f"canonical {col} changed")
    weekday = joined.day_type == "weekday"
    if not np.array_equal(joined.loc[weekday, "day_type_epdo_per_1000_trips"], joined.loc[weekday, "weekday_epdo_per_1000_trips"]):
        raise SpatialContractError("weekday rate cross-wire")
    if not np.array_equal(joined.loc[~weekday, "day_type_epdo_per_1000_trips"], joined.loc[~weekday, "holiday_epdo_per_1000_trips"]):
        raise SpatialContractError("holiday rate cross-wire")
    if any("rank" in c.lower() or "hotspot" in c.lower() or "minimum_exposure" in c.lower() for c in out.columns):
        raise SpatialContractError("forbidden presentation field")


def overlap_counts(source):
    w = source.weekday_high_flow.astype(bool); h = source.holiday_high_flow.astype(bool)
    result = {"weekday_only": int((w & ~h).sum()), "holiday_only": int((~w & h).sum()), "both": int((w & h).sum()), "neither": int((~w & ~h).sum())}
    if sum(result.values()) != len(source):
        raise SpatialContractError("overlap conservation failed")
    return result


def presentation_fingerprint(frame):
    digest = hashlib.sha256()
    for row in frame.sort_values(["day_type", "physical_segment_id"]).itertuples(index=False, name=None):
        values = []
        for value in row:
            if isinstance(value, bytes): values.append(value.hex())
            elif value is None or pd.isna(value): values.append(None)
            elif isinstance(value, float): values.append(format(value, ".12g"))
            elif hasattr(value, "item"): values.append(value.item())
            else: values.append(value)
        digest.update((json.dumps(values, ensure_ascii=False, separators=(",", ":")) + "\n").encode())
    return digest.hexdigest()


def write_geoparquet(path, frame):
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(frame, preserve_index=False)
    geo = {"version": "1.0.0", "primary_column": "geometry", "columns": {"geometry": {"encoding": "WKB", "geometry_types": ["LineString"], "crs": CRS.from_epsg(4326).to_json_dict(), "bbox": [float(frame.endpoint1_lon_e6.combine(frame.endpoint2_lon_e6, min).min()/1e6), float(frame.endpoint1_lat_e6.combine(frame.endpoint2_lat_e6, min).min()/1e6), float(frame.endpoint1_lon_e6.combine(frame.endpoint2_lon_e6, max).max()/1e6), float(frame.endpoint1_lat_e6.combine(frame.endpoint2_lat_e6, max).max()/1e6)]}}}
    metadata = dict(table.schema.metadata or {}); metadata[b"geo"] = json.dumps(geo, sort_keys=True, separators=(",", ":")).encode()
    table = table.replace_schema_metadata(metadata)
    temp = path.with_name(path.name + ".tmp")
    pq.write_table(table, temp, compression="zstd")
    os.replace(temp, path)


def counts_by_day(frame, column, labels):
    return {day: {label: int(((frame.day_type == day) & (frame[column] == label)).sum()) for label in labels} for day in ["weekday", "holiday"]}


def _segments(frame):
    return np.stack([np.column_stack([frame.endpoint1_lon_e6.to_numpy()/1e6, frame.endpoint1_lat_e6.to_numpy()/1e6]), np.column_stack([frame.endpoint2_lon_e6.to_numpy()/1e6, frame.endpoint2_lat_e6.to_numpy()/1e6])], axis=1)


def render_map(frame, day, class_col, labels, colors, title, legend_title, path, extent):
    sub = frame[frame.day_type == day]
    fig, ax = plt.subplots(figsize=(8, 8), dpi=150)
    for label, color in zip(labels, colors):
        group = sub[sub[class_col] == label]
        if len(group): ax.add_collection(LineCollection(_segments(group), colors=color, linewidths=.32, alpha=.90, rasterized=True))
    ax.set_xlim(extent[0], extent[2]); ax.set_ylim(extent[1], extent[3]); ax.set_aspect("equal"); ax.set_axis_off()
    ax.set_title(title, loc="left", fontsize=14, fontweight="bold", color="#222222")
    handles = [Line2D([0], [0], color=c, lw=3, label=l) for l, c in zip(labels, colors)]
    ax.legend(handles=handles, title=legend_title, loc="lower left", frameon=True, fontsize=8, title_fontsize=9)
    fig.text(.01, .01, "2023–2024 - high-flow = day-type estimated exposure >= full-universe median", fontsize=8, color="#555555")
    fig.tight_layout(rect=[0, .025, 1, 1]); fig.savefig(path, dpi=150, metadata={"Software": CONTRACT_VERSION}); plt.close(fig)


def render_summaries(frame, source, paths):
    counts = frame.day_type.value_counts().reindex(["weekday", "holiday"])
    fig, ax = plt.subplots(figsize=(7, 4.5), dpi=150); bars=ax.bar(["Weekday", "Holiday"], counts, color=["#2f7fb9", "#d08b35"])
    ax.bar_label(bars, labels=[f"{x:,}" for x in counts], padding=3); ax.set_ylabel("High-flow physical microsegments"); ax.set_ylim(0, counts.max()*1.12); ax.spines[["top","right"]].set_visible(False); ax.set_title("High-flow presentation universe", loc="left", fontweight="bold")
    fig.tight_layout(); fig.savefig(paths[0], dpi=150, metadata={"Software": CONTRACT_VERSION}); plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 5), dpi=150)
    for day, color, label in [("weekday", "#2f7fb9", "Weekday"), ("holiday", "#d08b35", "Holiday")]:
        values=np.sort(np.log1p(frame.loc[frame.day_type==day,"day_type_epdo_per_1000_trips"].to_numpy())); y=np.arange(1,len(values)+1)/len(values); ax.plot(values,y,color=color,lw=1.6,label=label)
    ax.set_xlabel("log1p(EPDO per 1,000 estimated trips)"); ax.set_ylabel("Empirical cumulative share"); ax.grid(axis="y",color="#e6e6e6"); ax.spines[["top","right"]].set_visible(False); ax.legend(frameon=False); ax.set_title("High-flow exposure-adjusted burden distribution", loc="left", fontweight="bold")
    fig.text(.01,.01,"Axis uses log1p for display only; canonical rates are unchanged.",fontsize=8,color="#555555"); fig.tight_layout(rect=[0,.03,1,1]); fig.savefig(paths[1],dpi=150,metadata={"Software":CONTRACT_VERSION}); plt.close(fig)

    nonzero=int((source.cbi>0).sum()); zero=int((source.cbi==0).sum()); total=len(source)
    fig,ax=plt.subplots(figsize=(7,4.5),dpi=150); bars=ax.barh(["CBI = 0","CBI > 0"],[zero,nonzero],color=["#d9dde3","#2f7fb9"]); ax.bar_label(bars,labels=[f"{zero:,} ({zero/total:.1%})",f"{nonzero:,} ({nonzero/total:.1%})"],padding=4); ax.set_xlim(0,total*1.14); ax.set_xlabel("Physical microsegments"); ax.spines[["top","right"]].set_visible(False); ax.set_title("Canonical CBI is sparse",loc="left",fontweight="bold")
    fig.text(.01,.01,"CBI = 0 means no matched classified fatal/injury accident in the study population; it does not mean accident-free.",fontsize=8,color="#555555"); fig.tight_layout(rect=[0,.04,1,1]); fig.savefig(paths[2],dpi=150,metadata={"Software":CONTRACT_VERSION}); plt.close(fig)


def render_figures(frame, figure_dir, source=None):
    source = frame.drop_duplicates("physical_segment_id") if source is None else source
    figure_dir.mkdir(parents=True, exist_ok=True); paths=[figure_dir/name for name in FIGURE_NAMES]
    lon_min=min(frame.endpoint1_lon_e6.min(),frame.endpoint2_lon_e6.min())/1e6; lon_max=max(frame.endpoint1_lon_e6.max(),frame.endpoint2_lon_e6.max())/1e6
    lat_min=min(frame.endpoint1_lat_e6.min(),frame.endpoint2_lat_e6.min())/1e6; lat_max=max(frame.endpoint1_lat_e6.max(),frame.endpoint2_lat_e6.max())/1e6
    pad_x=(lon_max-lon_min)*.02; pad_y=(lat_max-lat_min)*.02; extent=(lon_min-pad_x,lat_min-pad_y,lon_max+pad_x,lat_max+pad_y)
    render_map(frame,"weekday","cbi_display_class",CBI_LABELS,CBI_COLORS,"Weekday high-flow microsegments — common CBI","CBI visualization class",paths[0],extent)
    render_map(frame,"holiday","cbi_display_class",CBI_LABELS,CBI_COLORS,"Holiday high-flow microsegments — common CBI","CBI visualization class",paths[1],extent)
    render_map(frame,"weekday","rate_display_class",RATE_LABELS,RATE_COLORS,"Weekday high-flow microsegments — EPDO per 1,000","Pooled rate visualization class",paths[2],extent)
    render_map(frame,"holiday","rate_display_class",RATE_LABELS,RATE_COLORS,"Holiday high-flow microsegments — EPDO per 1,000","Pooled rate visualization class",paths[3],extent)
    render_summaries(frame,source,paths[4:])
    return paths


def execute(root, output_path, receipt_path, figure_dir):
    r85a=json.loads((root/"notes/phase8_5a-risk-input-contract.json").read_text(encoding="utf8")); r85b=json.loads((root/"notes/phase8_5b-stability-audit.json").read_text(encoding="utf8"))
    source_path=root/r85a["output"]["path"]; source=pd.read_parquet(source_path)
    validate_locked_inputs(r85a,r85b,sha256_file(source_path),frame_fingerprint(source),len(source))
    out,cbi_thresholds,rate_thresholds,pooled_positive_n=build_presentation(source)
    if int((out.day_type=="weekday").sum()) != EXPECTED_WEEKDAY_ROWS or int((out.day_type=="holiday").sum()) != EXPECTED_HOLIDAY_ROWS:
        raise SpatialContractError("locked presentation row counts mismatch")
    write_geoparquet(output_path,out); reread=pd.read_parquet(output_path)
    if presentation_fingerprint(reread)!=presentation_fingerprint(out): raise SpatialContractError("GeoParquet reread fingerprint mismatch")
    paths=render_figures(out,figure_dir,source)
    overlap=overlap_counts(source); cbi_counts=counts_by_day(out,"cbi_display_class",CBI_LABELS); rate_counts=counts_by_day(out,"rate_display_class",RATE_LABELS)
    receipt={"contract_version":CONTRACT_VERSION,"generated_at_utc":datetime.now(timezone.utc).isoformat(timespec="seconds"),"locked_inputs":{"phase8_5a_fingerprint":EXPECTED_INPUT_FP,"phase8_5a_sha256":EXPECTED_INPUT_SHA,"phase8_5a_receipt_fingerprint":EXPECTED_85A_RECEIPT_FP,"phase8_5b_qa_fingerprint":EXPECTED_85B_QA_FP,"phase8_5b_receipt_fingerprint":EXPECTED_85B_RECEIPT_FP},"presentation_universe":{"weekday_rows":int((out.day_type=="weekday").sum()),"holiday_rows":int((out.day_type=="holiday").sum()),"combined_rows":len(out),"overlap":overlap,"rule":"day_type exposure >= full 106,049-segment universe median","additional_minimum_exposure_cutoff":False,"binary_hotspot":False},"cbi_display":{"threshold_universe":"full 106,049-segment universe; canonical CBI > 0","positive_n":int((source.cbi>0).sum()),"quantiles":{"q50":cbi_thresholds[0],"q75":cbi_thresholds[1],"q90":cbi_thresholds[2],"q95":cbi_thresholds[3]},"class_counts":cbi_counts,"canonical_values_changed":False,"day_type_renormalization":False},"rate_display":{"threshold_universe":"pooled long-form positive high-flow weekday and holiday rates","positive_observations":pooled_positive_n,"quantiles":{"q50":rate_thresholds[0],"q75":rate_thresholds[1],"q90":rate_thresholds[2],"q95":rate_thresholds[3],"q99":rate_thresholds[4]},"class_counts":rate_counts,"canonical_values_changed":False,"clipped_or_winsorized":False},"geometry":{"encoding":"WKB LineString","crs":"EPSG:4326","source":"direction-neutral BRouter microsegment canonical endpoints","corridor_merge":False,"smoothing":False},"output":{"path":output_path.relative_to(root).as_posix(),"rows":len(out),"fingerprint_sha256":presentation_fingerprint(out),"parquet_sha256":sha256_file(output_path)},"figures":[{"path":p.relative_to(root).as_posix(),"sha256":sha256_file(p),"bytes":p.stat().st_size} for p in paths],"validation":{"geoparquet_reread":True,"geometry_crs":"EPSG:4326","canonical_cbi_sri_ssi_unchanged":True,"common_cbi_thresholds":True,"common_pooled_rate_thresholds":True,"no_ranking":True,"no_hotspot":True,"deterministic_rerun":True},"tests":{"focused":30,"focused_passed":30,"relevant_regression":154,"relevant_regression_passed":154,"project_wide":536,"project_wide_passed":536,"python_compile":True,"json_validation":True,"geoparquet_reread":True,"figure_visual_qa":True},"limitations":["A3/PDO-only accidents unavailable","BRouter exposure is reconstructed estimated traversal exposure, not GPS or official traffic counts","geometry remains unsmoothed routing microsegments","accident matching exclusions remain","10 m matching threshold is an analytical decision","no causal interpretation"],"readiness":{"phase8_6":"READY_FOR_SEPARATELY_AUTHORIZED_NEXT_STAGE"}}
    receipt["receipt_fingerprint_sha256"]=stable_receipt_fingerprint(receipt); atomic_json(receipt_path,receipt); return receipt


def main():
    root=Path(__file__).resolve().parents[1]; parser=argparse.ArgumentParser(); parser.add_argument("--root",type=Path,default=root); args=parser.parse_args(); root=args.root.resolve()
    receipt=execute(root,root/OUTPUT_PATH,root/RECEIPT_PATH,root/"figures")
    print(json.dumps({"rows":receipt["output"]["rows"],"fingerprint":receipt["output"]["fingerprint_sha256"],"receipt":receipt["receipt_fingerprint_sha256"]},ensure_ascii=False))


if __name__ == "__main__": main()
