import copy
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.build_interactive_case_review import (
    CLASS_COLORS,
    BASE_WIDTH_PX,
    HOVER_WIDTH_PX,
    EXPECTED_PHASE86A_QA_FP,
    PRIMARY_CLASSES,
    SECONDARY_CLASS,
    build_layer_records,
    derive_bounds,
    map_data_fingerprint,
    layer_hover_style,
    layer_style,
    localized_feature_collection,
    render_map,
    validate_locked_inputs,
)
from src.validate_accident_road_reference import SpatialContractError


def worksheet_fixture():
    rows = []
    specs = [
        ("a", "q90_q95", True, False, "weekday_only_candidate"),
        ("b", "above_q95", False, True, "holiday_only_candidate"),
        ("c", "above_q95", True, True, "both_daytypes_candidate"),
    ]
    for i, (segment, cls, weekday, holiday, state) in enumerate(specs):
        rows.append({
            "physical_segment_id": segment, "cbi": 0.3 + i / 10, "sri": 0.1,
            "ssi": 0.2 + i / 10, "cbi_display_class": cls, "accident_count": 2 + i,
            "fatal_accident_count": i == 2, "injury_accident_count": 2,
            "epdo": 234 + i * 193, "weekday_high_flow": weekday,
            "holiday_high_flow": holiday, "weekday_candidate_review": weekday,
            "holiday_candidate_review": holiday, "candidate_daytype_state": state,
            "weekday_exposure": 1000 + i, "holiday_exposure": 500 + i,
            "weekday_epdo_per_1000": 1.2 + i, "holiday_epdo_per_1000": 2.3 + i,
            "segment_length_m": 12.5 + i, "endpoint1_lon_e6": 121500000 + i * 100,
            "endpoint1_lat_e6": 25000000 + i * 100, "endpoint2_lon_e6": 121500100 + i * 100,
            "endpoint2_lat_e6": 25000100 + i * 100, "review_status": "", "researcher_note": "",
        })
    return pd.DataFrame(rows)


def presentation_fixture():
    rows = []
    for i in range(2592):
        for day in (["weekday", "holiday"] if i < 3 else ["weekday"]):
            rows.append({
                "day_type": day, "physical_segment_id": f"s{i:04d}",
                "cbi_display_class": SECONDARY_CLASS, "cbi": 0.15,
                "accident_count": 1, "epdo": 117,
                "endpoint1_lon_e6": 121000000 + i, "endpoint1_lat_e6": 25000000 + i,
                "endpoint2_lon_e6": 121000001 + i, "endpoint2_lat_e6": 25000001 + i,
            })
    return pd.DataFrame(rows)


class InteractiveCaseReviewTests(unittest.TestCase):
    def setUp(self):
        self.worksheet = worksheet_fixture()
        self.presentation = presentation_fixture()
        self.layers, self.secondary = build_layer_records(
            self.worksheet, self.presentation, enforce_production_counts=False
        )

    def test_01_primary_candidate_fixture_counts(self):
        self.assertEqual(sum(len(v) for (d, c), v in self.layers.items() if c in PRIMARY_CLASSES), 4)

    def test_02_secondary_unique_context_count(self):
        self.assertEqual(len(self.secondary), 2592)

    def test_03_weekday_membership(self):
        ids = {f["properties"]["physical_segment_id"] for key, values in self.layers.items() if key[0] == "weekday" and key[1] in PRIMARY_CLASSES for f in values}
        self.assertEqual(ids, {"a", "c"})

    def test_04_holiday_membership(self):
        ids = {f["properties"]["physical_segment_id"] for key, values in self.layers.items() if key[0] == "holiday" and key[1] in PRIMARY_CLASSES for f in values}
        self.assertEqual(ids, {"b", "c"})

    def test_05_both_membership(self):
        self.assertEqual(self.worksheet.query("candidate_daytype_state == 'both_daytypes_candidate'").physical_segment_id.tolist(), ["c"])

    def test_06_cbi_identical_between_day_copies(self):
        w = next(f for f in self.layers[("weekday", "above_q95")] if f["properties"]["physical_segment_id"] == "c")
        h = next(f for f in self.layers[("holiday", "above_q95")] if f["properties"]["physical_segment_id"] == "c")
        self.assertEqual(w["properties"]["cbi"], h["properties"]["cbi"])

    def test_07_popup_uses_canonical_cbi(self):
        feature = self.layers[("weekday", "q90_q95")][0]
        self.assertEqual(feature["properties"]["cbi"], "0.3000")

    def test_08_popup_uses_canonical_epdo(self):
        self.assertEqual(self.layers[("weekday", "q90_q95")][0]["properties"]["epdo"], "234")

    def test_09_popup_weekday_exposure(self):
        self.assertEqual(self.layers[("weekday", "q90_q95")][0]["properties"]["weekday_exposure"], "1,000")

    def test_10_popup_holiday_exposure(self):
        self.assertEqual(self.layers[("holiday", "above_q95")][0]["properties"]["holiday_exposure"], "501")

    def test_11_popup_weekday_rate(self):
        self.assertEqual(self.layers[("weekday", "q90_q95")][0]["properties"]["weekday_epdo_per_1000"], "1.200")

    def test_12_popup_holiday_rate(self):
        self.assertEqual(self.layers[("holiday", "above_q95")][0]["properties"]["holiday_epdo_per_1000"], "3.300")

    def test_13_geometry_preserved(self):
        coordinates = self.layers[("weekday", "q90_q95")][0]["geometry"]["coordinates"]
        self.assertEqual(coordinates, [[121.5, 25.0], [121.5001, 25.0001]])

    def test_14_primary_colors_reused(self):
        self.assertEqual(CLASS_COLORS["q90_q95"], "#3d82b8")
        self.assertEqual(CLASS_COLORS["above_q95"], "#153f67")

    def test_15_secondary_color_reused(self):
        self.assertEqual(CLASS_COLORS[SECONDARY_CLASS], "#e6b75c")

    def test_16_no_ranking_fields(self):
        self.assertFalse(any("rank" in key for values in self.layers.values() for f in values for key in f["properties"]))

    def test_17_no_hotspot_fields(self):
        self.assertFalse(any("hotspot" in key for values in self.layers.values() for f in values for key in f["properties"]))

    def test_18_no_automatic_selection(self):
        self.assertFalse(any("selected" in key for values in self.layers.values() for f in values for key in f["properties"]))

    def test_19_map_data_fingerprint_deterministic(self):
        shuffled = {key: list(reversed(values)) for key, values in self.layers.items()}
        for values in shuffled.values():
            values.sort(key=lambda f: f["properties"]["physical_segment_id"])
        self.assertEqual(map_data_fingerprint(self.layers), map_data_fingerprint(shuffled))

    def test_20_upstream_identity_mismatch_fails_closed(self):
        receipt86 = {"receipt_fingerprint_sha256": "bad", "qa_fingerprint_sha256": EXPECTED_PHASE86A_QA_FP}
        with self.assertRaises(SpatialContractError):
            validate_locked_inputs(receipt86, {}, self.worksheet, self.presentation, "bad", "bad")

    def test_21_bounds_are_derived_from_geometry(self):
        bounds = derive_bounds(self.layers)
        self.assertLess(bounds[0][0], bounds[1][0])
        self.assertLess(bounds[0][1], bounds[1][1])

    def test_22_rendered_html_has_traditional_chinese_ui_and_no_selection_ui(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "map.html"
            render_map(self.layers, output)
            text = output.read_text(encoding="utf-8")
            self.assertIn("平日", text)
            self.assertIn("假日", text)
            self.assertIn("Q75–Q90（次要脈絡）", text)
            self.assertIn("Q90–Q95（主要檢視）", text)
            self.assertIn("Q95 以上（主要檢視）", text)
            self.assertIn("視覺化級距僅用於縮小人工檢視範圍，不代表熱點定義或危險程度排名。", text)
            self.assertIn("\\u5fae\\u8def\\u6bb5\\u8b58\\u5225\\u78bc", text)
            self.assertIn("OpenStreetMap", text)
            self.assertNotIn("review_status", text)

    def test_23_committed_primary_and_secondary_counts(self):
        root = Path(__file__).resolve().parents[1]
        worksheet = pd.read_csv(root / "notes/phase8_6a-case-candidate-review.csv", keep_default_na=False)
        presentation = pd.read_parquet(root / "data/processed/risk/segment_risk_presentation_2023_2024.parquet")
        layers, secondary = build_layer_records(worksheet, presentation)
        self.assertEqual(len(worksheet), 1283)
        self.assertEqual(len(secondary), 2592)
        self.assertEqual(sum(len(layers[("weekday", c)]) for c in PRIMARY_CLASSES), 1270)
        self.assertEqual(sum(len(layers[("holiday", c)]) for c in PRIMARY_CLASSES), 1255)

    def test_24_primary_layers_use_equal_base_width(self):
        self.assertEqual(BASE_WIDTH_PX["q90_q95"], 5.5)
        self.assertEqual(BASE_WIDTH_PX["above_q95"], 5.5)

    def test_25_secondary_context_is_thinner(self):
        self.assertEqual(BASE_WIDTH_PX["q75_q90"], 3.0)
        self.assertLess(BASE_WIDTH_PX["q75_q90"], BASE_WIDTH_PX["q90_q95"])

    def test_26_hover_only_changes_display_style(self):
        self.assertEqual(layer_hover_style("q90_q95")["weight"], 7.5)
        self.assertEqual(layer_hover_style("above_q95")["weight"], 7.5)
        self.assertEqual(layer_hover_style("q75_q90")["weight"], 5.0)
        self.assertNotIn("cbi", layer_style("q90_q95"))
        self.assertNotIn("cbi", layer_hover_style("q90_q95"))

    def test_27_localization_does_not_mutate_canonical_feature(self):
        source = self.layers[("weekday", "q90_q95")][0]
        before = copy.deepcopy(source)
        localized = localized_feature_collection([source])["features"][0]
        self.assertEqual(source, before)
        self.assertEqual(localized["properties"]["weekday_high_flow"], "是")
        self.assertEqual(localized["properties"]["holiday_high_flow"], "否")
        self.assertEqual(localized["properties"]["candidate_daytype_state"], "僅平日")
        self.assertEqual(localized["properties"]["cbi_display_class"], "Q90–Q95（主要檢視）")

    def test_28_no_new_cutoff_field(self):
        self.assertFalse(any("cutoff" in key for values in self.layers.values() for f in values for key in f["properties"]))


if __name__ == "__main__":
    unittest.main()
