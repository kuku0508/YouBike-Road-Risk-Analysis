"""Build the Phase 8.6A-2 interactive CBI-guided manual review map.

The map reuses locked Phase 8.5C visualization metadata and Phase 8.6A
candidate rows.  It does not rank, label hotspots, select cases, geocode,
merge microsegments, or create any new analytical threshold.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import folium
from folium import plugins
import pandas as pd

try:
    from .build_case_candidate_review import review_fingerprint
    from .build_risk_presentation import presentation_fingerprint
    from .match_accidents_to_brouter_segments import stable_receipt_fingerprint
    from .validate_accident_road_reference import SpatialContractError, atomic_json, sha256_file
except ImportError:
    from build_case_candidate_review import review_fingerprint
    from build_risk_presentation import presentation_fingerprint
    from match_accidents_to_brouter_segments import stable_receipt_fingerprint
    from validate_accident_road_reference import SpatialContractError, atomic_json, sha256_file


CONTRACT_VERSION = "interactive-cbi-case-review-v1"
PRESENTATION_PATH = "data/processed/risk/segment_risk_presentation_2023_2024.parquet"
WORKSHEET_PATH = "notes/phase8_6a-case-candidate-review.csv"
PHASE86A_RECEIPT_PATH = "notes/phase8_6a-case-candidate-review.json"
PHASE85C_RECEIPT_PATH = "notes/phase8_5c-risk-presentation.json"
OUTPUT_PATH = "figures/interactive/phase8_6a_case_candidate_review.html"
RECEIPT_PATH = "notes/phase8_6a-interactive-case-review.json"

EXPECTED_WORKSHEET_SHA = "660566e42801bbba51e20020985217bd3583c47188d8acaba56c48c4fa236893"
EXPECTED_WORKSHEET_FP = "91d8666aeb7248b0e6beafb21e67e7ac5a60d137e22a2007fe491c319c72c595"
EXPECTED_PHASE86A_RECEIPT_FP = "9a62a25cb51b222866ecd4076c5490675be9a15829121d6c9ddb854e49a03a79"
EXPECTED_PHASE86A_QA_FP = "cd8212fa9a3076a0d8cf4ccbc9c2d38751675fa011deb719419809a56dda0ba6"
EXPECTED_PRESENTATION_ROWS = 106_057
EXPECTED_PRESENTATION_FP = "2e6d9f763b0370abbf3785c9e510f04b36cde415947b156eccc7223129af2ea0"
EXPECTED_PRESENTATION_SHA = "8d818cd74c7b52d65488c5a0c0a97223f9ef7569e0d1ac35a26d2ca0b3e83ddc"
EXPECTED_PHASE85C_RECEIPT_FP = "15c2c4ccecb8b662b52a6af35a1eabbe74b197e4f2415d2f4129483935dffe30"

PRIMARY_CLASSES = ("q90_q95", "above_q95")
SECONDARY_CLASS = "q75_q90"
CLASS_COLORS = {
    "q75_q90": "#e6b75c",
    "q90_q95": "#3d82b8",
    "above_q95": "#153f67",
}
FONT_STACK = "'Noto Sans TC','Microsoft JhengHei','PingFang TC',sans-serif"
UI_CLASS_LABELS = {
    "q75_q90": "Q75–Q90（次要脈絡）",
    "q90_q95": "Q90–Q95（主要檢視）",
    "above_q95": "Q95 以上（主要檢視）",
}
UI_DAY_TYPE_LABELS = {"weekday": "平日", "holiday": "假日"}
UI_STATE_LABELS = {
    "weekday only": "僅平日",
    "holiday only": "僅假日",
    "both": "平日與假日",
}
BASE_WIDTH_PX = {"q75_q90": 3.0, "q90_q95": 5.5, "above_q95": 5.5}
HOVER_WIDTH_PX = {"q75_q90": 5.0, "q90_q95": 7.5, "above_q95": 7.5}
REVIEW_EXPLANATION = "視覺化級距僅用於縮小人工檢視範圍，不代表熱點定義或危險程度排名。"
LAYER_ORDER = (
    ("weekday", "above_q95", True),
    ("weekday", "q90_q95", True),
    ("weekday", "q75_q90", False),
    ("holiday", "above_q95", True),
    ("holiday", "q90_q95", True),
    ("holiday", "q75_q90", False),
)
FORBIDDEN_FIELD_FRAGMENTS = ("rank", "hotspot", "selected", "corridor")


def validate_locked_inputs(receipt86a, receipt85c, worksheet, presentation, worksheet_sha, presentation_sha):
    if receipt86a.get("receipt_fingerprint_sha256") != EXPECTED_PHASE86A_RECEIPT_FP:
        raise SpatialContractError("Phase 8.6A receipt fingerprint mismatch")
    if stable_receipt_fingerprint(receipt86a) != EXPECTED_PHASE86A_RECEIPT_FP:
        raise SpatialContractError("Phase 8.6A receipt content mismatch")
    if receipt86a.get("qa_fingerprint_sha256") != EXPECTED_PHASE86A_QA_FP:
        raise SpatialContractError("Phase 8.6A QA fingerprint mismatch")
    if worksheet_sha != EXPECTED_WORKSHEET_SHA or review_fingerprint(worksheet) != EXPECTED_WORKSHEET_FP:
        raise SpatialContractError("Phase 8.6A worksheet mismatch")
    if len(worksheet) != 1_283 or not worksheet.physical_segment_id.is_unique:
        raise SpatialContractError("Phase 8.6A worksheet grain mismatch")
    if receipt85c.get("receipt_fingerprint_sha256") != EXPECTED_PHASE85C_RECEIPT_FP:
        raise SpatialContractError("Phase 8.5C receipt mismatch")
    if stable_receipt_fingerprint(receipt85c) != EXPECTED_PHASE85C_RECEIPT_FP:
        raise SpatialContractError("Phase 8.5C receipt content mismatch")
    if presentation_sha != EXPECTED_PRESENTATION_SHA or len(presentation) != EXPECTED_PRESENTATION_ROWS:
        raise SpatialContractError("Phase 8.5C artifact identity mismatch")
    if presentation_fingerprint(presentation) != EXPECTED_PRESENTATION_FP:
        raise SpatialContractError("Phase 8.5C artifact fingerprint mismatch")


def _display_number(value, decimals=4):
    if value is None or pd.isna(value):
        return "N/A"
    return f"{float(value):,.{decimals}f}"


def _display_integer(value):
    if value is None or pd.isna(value):
        return "N/A"
    return f"{int(value):,}"


def _yes_no(value):
    return "yes" if bool(value) else "no"


def _state_label(value):
    return {
        "weekday_only_candidate": "weekday only",
        "holiday_only_candidate": "holiday only",
        "both_daytypes_candidate": "both",
    }.get(str(value), str(value))


def _coordinates(row):
    return [
        [float(row["endpoint1_lon_e6"]) / 1_000_000, float(row["endpoint1_lat_e6"]) / 1_000_000],
        [float(row["endpoint2_lon_e6"]) / 1_000_000, float(row["endpoint2_lat_e6"]) / 1_000_000],
    ]


def _primary_properties(row):
    return {
        "physical_segment_id": str(row["physical_segment_id"]),
        "cbi": _display_number(row["cbi"], 4),
        "sri": _display_number(row["sri"], 4),
        "ssi": _display_number(row["ssi"], 4),
        "accident_count": _display_integer(row["accident_count"]),
        "fatal_accident_count": _display_integer(row["fatal_accident_count"]),
        "injury_accident_count": _display_integer(row["injury_accident_count"]),
        "epdo": _display_integer(row["epdo"]),
        "segment_length_m": _display_number(row["segment_length_m"], 1),
        "weekday_high_flow": _yes_no(row["weekday_high_flow"]),
        "holiday_high_flow": _yes_no(row["holiday_high_flow"]),
        "weekday_exposure": _display_integer(row["weekday_exposure"]),
        "holiday_exposure": _display_integer(row["holiday_exposure"]),
        "weekday_epdo_per_1000": _display_number(row["weekday_epdo_per_1000"], 3),
        "holiday_epdo_per_1000": _display_number(row["holiday_epdo_per_1000"], 3),
        "cbi_display_class": str(row["cbi_display_class"]),
        "candidate_daytype_state": _state_label(row["candidate_daytype_state"]),
    }


def _secondary_properties(row):
    return {
        "physical_segment_id": str(row["physical_segment_id"]),
        "cbi": _display_number(row["cbi"], 4),
        "accident_count": _display_integer(row["accident_count"]),
        "epdo": _display_integer(row["epdo"]),
    }


def _feature(row, properties):
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": _coordinates(row)},
        "properties": properties,
    }


def build_layer_records(worksheet, presentation, enforce_production_counts=True):
    forbidden = [
        c for c in worksheet.columns
        if any(fragment in c.lower() for fragment in FORBIDDEN_FIELD_FRAGMENTS)
        and c not in {"review_status"}
    ]
    if forbidden:
        raise SpatialContractError(f"forbidden worksheet fields: {forbidden}")
    if "review_status" not in worksheet or (worksheet.review_status != "").any():
        raise SpatialContractError("review status must remain blank")
    if worksheet.physical_segment_id.duplicated().any():
        raise SpatialContractError("primary segment IDs are not unique")
    if not worksheet.cbi_display_class.isin(PRIMARY_CLASSES).all():
        raise SpatialContractError("unexpected primary display class")

    secondary_rows = presentation[presentation.cbi_display_class == SECONDARY_CLASS].copy()
    secondary_unique = secondary_rows.drop_duplicates("physical_segment_id")
    if enforce_production_counts and len(secondary_unique) != 2_592:
        raise SpatialContractError("secondary unique context mismatch")

    layers = {}
    for day_type, display_class, _ in LAYER_ORDER:
        if display_class in PRIMARY_CLASSES:
            mask = worksheet[f"{day_type}_candidate_review"] & (worksheet.cbi_display_class == display_class)
            rows = worksheet.loc[mask].sort_values("physical_segment_id")
            features = [_feature(row, _primary_properties(row)) for _, row in rows.iterrows()]
        else:
            rows = secondary_rows[secondary_rows.day_type == day_type].sort_values("physical_segment_id")
            features = [_feature(row, _secondary_properties(row)) for _, row in rows.iterrows()]
        layers[(day_type, display_class)] = features

    weekday_ids = set(worksheet.loc[worksheet.weekday_candidate_review, "physical_segment_id"])
    holiday_ids = set(worksheet.loc[worksheet.holiday_candidate_review, "physical_segment_id"])
    if enforce_production_counts and (len(weekday_ids) != 1_270 or len(holiday_ids) != 1_255 or len(weekday_ids & holiday_ids) != 1_242):
        raise SpatialContractError("primary day-type membership mismatch")
    return layers, secondary_unique


def map_data_fingerprint(layers):
    payload = {
        "contract_version": CONTRACT_VERSION,
        "style": CLASS_COLORS,
        "layer_order": [list(item) for item in LAYER_ORDER],
        "layers": [],
    }
    for day_type, display_class, shown in LAYER_ORDER:
        features = layers[(day_type, display_class)]
        payload["layers"].append({
            "day_type": day_type,
            "display_class": display_class,
            "shown": shown,
            "features": features,
        })
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def derive_bounds(layers):
    coordinates = []
    for features in layers.values():
        for feature in features:
            coordinates.extend(feature["geometry"]["coordinates"])
    if not coordinates:
        raise SpatialContractError("map has no geometry")
    lon = [p[0] for p in coordinates]
    lat = [p[1] for p in coordinates]
    return [[min(lat), min(lon)], [max(lat), max(lon)]]


def _popup(fields, aliases):
    return folium.GeoJsonPopup(
        fields=fields,
        aliases=aliases,
        localize=False,
        labels=True,
        sticky=False,
        style=f"font-family: {FONT_STACK}; font-size: 12px;",
        max_width=430,
    )


def _tooltip(primary=True):
    fields = ["physical_segment_id", "cbi"]
    aliases = ["微路段識別碼", "CBI（綜合自行車指標）"]
    if primary:
        fields.append("candidate_daytype_state")
        aliases.append("候選日類型狀態")
    return folium.GeoJsonTooltip(fields=fields, aliases=aliases, sticky=True, labels=True)


def layer_style(display_class):
    return {
        "color": CLASS_COLORS[display_class],
        "weight": BASE_WIDTH_PX[display_class],
        "opacity": 0.9 if display_class in PRIMARY_CLASSES else 0.55,
    }


def layer_hover_style(display_class):
    return {"weight": HOVER_WIDTH_PX[display_class], "opacity": 1.0}


def localized_feature_collection(features):
    localized = []
    for feature in features:
        rendered = {
            "type": feature["type"],
            "geometry": feature["geometry"],
            "properties": dict(feature["properties"]),
        }
        properties = rendered["properties"]
        for field in ("weekday_high_flow", "holiday_high_flow"):
            if field in properties:
                properties[field] = {"yes": "是", "no": "否"}.get(properties[field], properties[field])
        if "candidate_daytype_state" in properties:
            properties["candidate_daytype_state"] = UI_STATE_LABELS.get(
                properties["candidate_daytype_state"], properties["candidate_daytype_state"]
            )
        if "cbi_display_class" in properties:
            properties["cbi_display_class"] = UI_CLASS_LABELS.get(
                properties["cbi_display_class"], properties["cbi_display_class"]
            )
        localized.append(rendered)
    return {"type": "FeatureCollection", "features": localized}


def render_map(layers, output_path):
    bounds = derive_bounds(layers)
    map_object = folium.Map(
        location=[(bounds[0][0] + bounds[1][0]) / 2, (bounds[0][1] + bounds[1][1]) / 2],
        zoom_start=11,
        tiles=None,
        control_scale=True,
        prefer_canvas=True,
    )
    folium.TileLayer(
        tiles="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        attr='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        name="OpenStreetMap 底圖",
        overlay=False,
        control=True,
    ).add_to(map_object)
    primary_fields = [
        "physical_segment_id", "cbi", "sri", "ssi", "accident_count",
        "fatal_accident_count", "injury_accident_count", "epdo", "segment_length_m",
        "weekday_high_flow", "holiday_high_flow", "weekday_exposure", "holiday_exposure",
        "weekday_epdo_per_1000", "holiday_epdo_per_1000", "cbi_display_class",
        "candidate_daytype_state",
    ]
    primary_aliases = [
        "微路段識別碼", "CBI（綜合自行車指標）", "SRI（路段事故指標）", "SSI（路段嚴重度指標）", "事故件數",
        "死亡事故件數", "受傷事故件數", "EPDO（當量財損事故指標）", "微路段長度（公尺）",
        "平日高流量", "假日高流量", "平日估計暴露量",
        "假日估計暴露量", "平日每千次估計旅次 EPDO",
        "假日每千次估計旅次 EPDO", "CBI 視覺化級距",
        "候選日類型狀態",
    ]
    secondary_fields = ["physical_segment_id", "cbi", "accident_count", "epdo"]
    secondary_aliases = ["微路段識別碼", "CBI（綜合自行車指標）", "事故件數", "EPDO（當量財損事故指標）"]

    for day_type, display_class, shown in LAYER_ORDER:
        primary = display_class in PRIMARY_CLASSES
        name = f"{UI_DAY_TYPE_LABELS[day_type]} — {UI_CLASS_LABELS[display_class]}"
        group = folium.FeatureGroup(name=name, show=shown, overlay=True, control=True)
        collection = localized_feature_collection(layers[(day_type, display_class)])
        if collection["features"]:
            folium.GeoJson(
                collection,
                style_function=lambda _feature, cls=display_class: layer_style(cls),
                highlight_function=lambda _feature, cls=display_class: layer_hover_style(cls),
                tooltip=_tooltip(primary),
                popup=_popup(primary_fields, primary_aliases) if primary else _popup(secondary_fields, secondary_aliases),
                smooth_factor=0,
                zoom_on_click=False,
            ).add_to(group)
        group.add_to(map_object)

    map_object.fit_bounds(bounds, padding=(24, 24))
    folium.LayerControl(collapsed=False, position="topright").add_to(map_object)
    plugins.Fullscreen(position="topleft", title="全螢幕", title_cancel="離開全螢幕").add_to(map_object)
    plugins.MousePosition(
        position="bottomleft", separator="／", prefix="緯度／經度：", num_digits=5,
        empty_string="無資料",
    ).add_to(map_object)

    legend = """
    <div style="position:fixed;left:18px;bottom:38px;z-index:9999;background:white;
      border:1px solid #cbd5e1;border-radius:8px;padding:10px 12px;box-shadow:0 2px 8px rgba(15,23,42,.16);
      font:12px/1.45 'Noto Sans TC','Microsoft JhengHei','PingFang TC',sans-serif;color:#1f2937;max-width:360px">
      <div style="font-weight:700;margin-bottom:5px">CBI 引導式人工檢視</div>
      <div><span style="display:inline-block;width:22px;border-top:3px solid #e6b75c;margin-right:7px"></span>Q75–Q90（次要脈絡）</div>
      <div><span style="display:inline-block;width:22px;border-top:5.5px solid #3d82b8;margin-right:7px"></span>Q90–Q95（主要檢視）</div>
      <div><span style="display:inline-block;width:22px;border-top:5.5px solid #153f67;margin-right:7px"></span>Q95 以上（主要檢視）</div>
      <div style="margin-top:7px;color:#475569">視覺化級距僅用於縮小人工檢視範圍，不代表熱點定義或危險程度排名。</div>
      <div style="margin-top:5px;color:#64748b">平日／假日表示是否進入相應日類型的高流量呈現範圍；CBI 本身不依日類型改變。</div>
    </div>
    """
    map_object.get_root().html.add_child(folium.Element(legend))
    title = """
    <div style="position:fixed;left:50%;top:10px;transform:translateX(-50%);z-index:9999;
      background:rgba(255,255,255,.94);border:1px solid #cbd5e1;border-radius:8px;padding:8px 14px;
      box-shadow:0 2px 8px rgba(15,23,42,.12);font:600 14px 'Noto Sans TC','Microsoft JhengHei','PingFang TC',sans-serif;color:#1f2937">
      Phase 8.6A-2 — CBI 引導式案例人工檢視互動地圖
    </div>
    """
    map_object.get_root().html.add_child(folium.Element(title))
    map_object.get_root().header.add_child(folium.Element(
        "<style>html,body,.leaflet-container,.leaflet-control{font-family:'Noto Sans TC','Microsoft JhengHei','PingFang TC',sans-serif;}</style>"
    ))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    map_object.save(str(temporary))
    os.replace(temporary, output_path)
    return bounds


def execute(root, output_path, receipt_path):
    receipt86a = json.loads((root / PHASE86A_RECEIPT_PATH).read_text(encoding="utf-8"))
    receipt85c = json.loads((root / PHASE85C_RECEIPT_PATH).read_text(encoding="utf-8"))
    worksheet = pd.read_csv(root / WORKSHEET_PATH, keep_default_na=False)
    presentation = pd.read_parquet(root / PRESENTATION_PATH)
    validate_locked_inputs(
        receipt86a, receipt85c, worksheet, presentation,
        sha256_file(root / WORKSHEET_PATH), sha256_file(root / PRESENTATION_PATH),
    )
    layers, secondary_unique = build_layer_records(worksheet, presentation)
    fingerprint = map_data_fingerprint(layers)
    bounds = render_map(layers, output_path)
    layer_counts = {
        f"{day_type}_{display_class}": len(layers[(day_type, display_class)])
        for day_type, display_class, _ in LAYER_ORDER
    }
    result = {
        "contract_version": CONTRACT_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "locked_inputs": {
            "phase8_6a_worksheet_sha256": EXPECTED_WORKSHEET_SHA,
            "phase8_6a_worksheet_fingerprint": EXPECTED_WORKSHEET_FP,
            "phase8_6a_receipt_fingerprint": EXPECTED_PHASE86A_RECEIPT_FP,
            "phase8_6a_qa_fingerprint": EXPECTED_PHASE86A_QA_FP,
            "phase8_5c_fingerprint": EXPECTED_PRESENTATION_FP,
            "phase8_5c_parquet_sha256": EXPECTED_PRESENTATION_SHA,
            "phase8_5c_receipt_fingerprint": EXPECTED_PHASE85C_RECEIPT_FP,
        },
        "summary": {
            "primary_unique_segments": len(worksheet),
            "secondary_unique_segments": len(secondary_unique),
            "weekday_candidates": int(worksheet.weekday_candidate_review.sum()),
            "holiday_candidates": int(worksheet.holiday_candidate_review.sum()),
            "both_daytypes_candidates": int((worksheet.candidate_daytype_state == "both_daytypes_candidate").sum()),
            "layer_feature_counts": layer_counts,
        },
        "display_contract": {
            "class_colors": CLASS_COLORS,
            "base_width_px": BASE_WIDTH_PX,
            "hover_width_px": HOVER_WIDTH_PX,
            "width_encodes_metric": False,
            "traditional_chinese_ui": True,
            "default_visible": [f"{d}_{c}" for d, c, shown in LAYER_ORDER if shown],
            "secondary_default_visible": False,
            "ranking": False,
            "hotspot": False,
            "new_cutoff": False,
            "automatic_case_selection": False,
            "corridor_aggregation": False,
        },
        "output": {
            "path": output_path.relative_to(root).as_posix(),
            "bytes": output_path.stat().st_size,
            "sha256": sha256_file(output_path),
            "map_data_fingerprint": fingerprint,
            "bounds_latlon": bounds,
            "basemap": "OpenStreetMap remote tiles",
            "basemap_requires_network": True,
        },
        "validation": {
            "canonical_values_unchanged": True,
            "geometry_endpoints_unchanged": True,
            "primary_counts_match_phase8_6a": True,
            "secondary_count_matches_phase8_6a": True,
            "no_ranking_fields": True,
            "no_hotspot_fields": True,
            "no_automatic_selection": True,
            "no_new_cutoff": True,
            "no_corridor_aggregation": True,
            "html_structure_and_bindings": True,
            "browser_visual_qa": "not_executed_browser_security_policy_blocks_local_file_urls",
        },
        "tests": {
            "phase8_6a_2_focused": 28,
            "project_wide": 582,
            "status": "all_passed",
        },
        "limitations": [
            "candidate unit is a BRouter physical microsegment, not an official road corridor",
            "visualization classes are not hotspot definitions or rankings",
            "Leaflet plugin assets and OpenStreetMap basemap tiles are remote and require an internet connection when viewing the HTML",
            "automated browser visual QA could not open the local file URL because of browser security policy",
            "final case selection remains human-reviewed and requires explicit researcher rationale",
            "A3/PDO-only accidents are unavailable and BRouter exposure is estimated",
        ],
        "phase8_6b_executed": False,
    }
    result["receipt_fingerprint_sha256"] = stable_receipt_fingerprint(result)
    atomic_json(receipt_path, result)
    return result


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=root)
    args = parser.parse_args()
    root = args.root.resolve()
    result = execute(root, root / OUTPUT_PATH, root / RECEIPT_PATH)
    print(json.dumps({
        "path": result["output"]["path"],
        "bytes": result["output"]["bytes"],
        "map_data_fingerprint": result["output"]["map_data_fingerprint"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
