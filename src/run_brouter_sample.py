"""Run only the deterministic Phase 8.0 bounded BRouter sample."""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time
import urllib.parse
import urllib.request
from pathlib import Path

import matplotlib.pyplot as plt

from audit_routing_contract import haversine, load_sources, choose_coordinate, sha256_file
from route_segment_utils import parse_geojson_route


def get_route(base_url, origin, destination, timeout):
    params = urllib.parse.urlencode({
        "lonlats": f"{origin[0]},{origin[1]}|{destination[0]},{destination[1]}",
        "profile": "trekking", "alternativeidx": 0, "format": "geojson",
        "exportWaypoints": 1,
    }, safe="|,")
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(f"{base_url}?{params}", timeout=timeout) as response:
            raw = response.read()
        elapsed = time.perf_counter() - started
        parsed = parse_geojson_route(json.loads(raw))
        coordinates = parsed["coordinates"]
        props = parsed["properties"]
        distance = props.get("track-length", props.get("distance"))
        return {"status":"success", "runtime_seconds":elapsed, "response_bytes":len(raw),
                "output_sha256":hashlib.sha256(raw).hexdigest(), "route_hash":parsed["route_hash"],
                "route_distance_m":float(distance) if distance is not None else None,
                "segment_count":parsed["segment_count"], "unique_segment_count":len(set(parsed["segments"])),
                "repeated_segment_traversals":len(parsed["segments"])-len(set(parsed["segments"])),
                "origin_snap_offset_m":haversine(origin, tuple(coordinates[0][:2])),
                "destination_snap_offset_m":haversine(destination, tuple(coordinates[-1][:2])),
                "coordinates":coordinates}
    except TimeoutError as exc:
        return {"status":"timeout", "runtime_seconds":time.perf_counter()-started, "error":repr(exc)}
    except Exception as exc:
        return {"status":"brouter_error", "runtime_seconds":time.perf_counter()-started, "error":repr(exc)}


def percentile(values, q):
    values=sorted(values)
    if not values: return None
    idx=(len(values)-1)*q; lo=int(idx); hi=min(lo+1,len(values)-1); frac=idx-lo
    return values[lo]*(1-frac)+values[hi]*frac


def main(args):
    root=args.receipt.resolve().parents[1]
    rel=lambda path: path.resolve().relative_to(root).as_posix()
    receipt=json.loads(args.receipt.read_text(encoding="utf-8"))
    sources=load_sources(args.historical,args.taipei_current,args.nt_current)
    coords={sid:coord for sid,entries in sources.items() if (coord:=choose_coordinate(entries)[0]) is not None}
    sample=receipt["bounded_sample"]["definition"]
    runs=[]
    for run_index in (1,2):
        results=[]
        for item in sample:
            origin_id,destination_id=item["pair"].split("->")
            if origin_id==destination_id:
                result={"status":"self_loop_not_routed","runtime_seconds":0.0}
            elif origin_id not in coords or destination_id not in coords:
                result={"status":"coordinate_conflict","runtime_seconds":0.0}
            else:
                result=get_route(args.base_url,coords[origin_id],coords[destination_id],args.timeout)
            results.append({**item,"origin_station_id":origin_id,"destination_station_id":destination_id,**result})
        runs.append({"run_index":run_index,"results":results})
    primary=runs[0]["results"]
    rerun=runs[1]["results"]
    comparable=[(a,b) for a,b in zip(primary,rerun) if a["status"]==b["status"]=="success"]
    deterministic=all(a["route_hash"]==b["route_hash"] and a["route_distance_m"]==b["route_distance_m"] for a,b in comparable)
    success=[x for x in primary if x["status"]=="success"]
    nonself=[x for x in primary if x["status"]!="self_loop_not_routed"]
    runtimes=[x["runtime_seconds"] for x in success]
    sizes=[x["response_bytes"] for x in success]
    distances=[x["route_distance_m"] for x in success if x["route_distance_m"] is not None]
    segcounts=[x["segment_count"] for x in success]
    offsets=[v for x in success for v in (x["origin_snap_offset_m"],x["destination_snap_offset_m"])]
    total_edges=receipt["od"]["eligible_non_self_edges"]
    summary={
        "sample_non_self_count":len(nonself), "success_count":len(success),
        "success_rate":len(success)/len(nonself),
        "sample_trip_weight":sum(x["trip_count"] for x in nonself),
        "successful_trip_weight":sum(x["trip_count"] for x in success),
        "trip_weight_coverage":sum(x["trip_count"] for x in success)/sum(x["trip_count"] for x in nonself),
        "failure_status_counts":{s:sum(x["status"]==s for x in primary) for s in sorted(set(x["status"] for x in primary))},
        "runtime_seconds":{"median":statistics.median(runtimes),"p90":percentile(runtimes,.9)},
        "response_bytes":{"median":statistics.median(sizes),"p90":percentile(sizes,.9)},
        "route_distance_m":{"min":min(distances),"median":statistics.median(distances),"max":max(distances)},
        "segment_count":{"min":min(segcounts),"median":statistics.median(segcounts),"max":max(segcounts)},
        "snap_offset_m":{"max":max(offsets),"bins":{"le_25":sum(v<=25 for v in offsets),"25_50":sum(25<v<=50 for v in offsets),"50_100":sum(50<v<=100 for v in offsets),"gt_100":sum(v>100 for v in offsets)}},
        "repeated_segment_routes":sum(x["repeated_segment_traversals"]>0 for x in success),
        "deterministic_rerun":{"comparable_routes":len(comparable),"all_statuses_equal":all(a["status"]==b["status"] for a,b in zip(primary,rerun)),"route_hash_and_distance_equal":deterministic},
        "engineering_estimate":{"eligible_non_self_edges":total_edges,
            "single_worker_hours_at_sample_median":total_edges*statistics.median(runtimes)/3600,
            "single_worker_hours_at_sample_p90":total_edges*percentile(runtimes,.9)/3600,
            "raw_response_gib_at_sample_median":total_edges*statistics.median(sizes)/(1024**3)},
    }
    output={"contract_version":"road-routing-contract-v1","base_url":args.base_url,
            "brouter_version":"1.7.10","runs":runs,"summary":summary}
    args.output.write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    fig,axes=plt.subplots(2,2,figsize=(10,9));
    for ax,item in zip(axes.flat,success[:4]):
        xy=item["coordinates"]; ax.plot([p[0] for p in xy],[p[1] for p in xy],linewidth=1.4)
        ax.scatter([xy[0][0],xy[-1][0]],[xy[0][1],xy[-1][1]],c=["green","red"],s=28,zorder=3)
        ax.set_title(item["pair"]); ax.set_aspect("equal",adjustable="datalim"); ax.grid(alpha=.25)
        ax.set_xlabel("longitude"); ax.set_ylabel("latitude")
    fig.suptitle("BRouter v1.7.10 bounded route QA — Trekking / 2026-09-18 graph")
    fig.tight_layout(); args.figure.parent.mkdir(parents=True,exist_ok=True); fig.savefig(args.figure,dpi=160); plt.close(fig)
    receipt["brouter_environment"]={"status":"pinned_and_validated","brouter_version":"1.7.10",
        "java_version":"25.0.4.1","release_zip_sha256":sha256_file(args.release_zip),
        "jar_path":rel(args.jar),"jar_sha256":sha256_file(args.jar),"profile_path":rel(args.profile),
        "profile_sha256":sha256_file(args.profile),"routing_graph":[{"path":rel(p),"sha256":sha256_file(p)} for p in args.graph]}
    receipt["bounded_sample"].update({"routing_executed":True,"results_path":rel(args.output),"summary":summary})
    receipt["validation_status"]="blocked_station_coordinates"
    args.receipt.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False))


if __name__=="__main__":
    root=Path(__file__).resolve().parents[1]; base=root/"data/raw/routing/brouter-v1.7.10/brouter-1.7.10"
    p=argparse.ArgumentParser(); p.add_argument("--base-url",default="http://127.0.0.1:17777/brouter")
    p.add_argument("--timeout",type=int,default=120); p.add_argument("--receipt",type=Path,default=root/"notes/brouter-contract-validation.json")
    p.add_argument("--output",type=Path,default=root/"notes/brouter-bounded-results.json"); p.add_argument("--figure",type=Path,default=root/"reports/figures/brouter_bounded_routes.png")
    p.add_argument("--historical",type=Path,default=root/"data/raw/station_snapshot_2024-05-31.csv"); p.add_argument("--taipei-current",type=Path,default=root/"data/raw/youbike_immediate_2026-09-13.json"); p.add_argument("--nt-current",type=Path,default=root/"data/raw/new_taipei_youbike_2026-09-14.csv")
    p.add_argument("--release-zip",type=Path,default=root/"data/raw/routing/brouter-v1.7.10.zip"); p.add_argument("--jar",type=Path,default=base/"brouter-1.7.10-all.jar"); p.add_argument("--profile",type=Path,default=base/"profiles2/trekking.brf")
    p.add_argument("--graph",type=Path,nargs=2,default=[root/"data/raw/routing/E120_N20_20260918.rd5",root/"data/raw/routing/E120_N25_20260918.rd5"])
    main(p.parse_args())
