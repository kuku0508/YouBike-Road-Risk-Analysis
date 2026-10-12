from pathlib import Path
import sys
import unittest

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from aggregate_primary_od import (POLICY_VERSION, aggregate_frames, combine_edges,
                                  edge_statistics, resolve_endpoint, validate_policy, write_parquet)


class PrimaryODAggregationTests(unittest.TestCase):
    def setUp(self):
        self.evidence = {"unique_names": {"A": ("T1", "Taipei"), "A old": ("T1", "Taipei"),
                                           "B": ("T2", "Taipei")},
                         "collision_names": {}, "station_universe": {"TlRQ": ("N1", "New Taipei")}}

    def frame(self):
        def row(origin, destination, origin_status="unchanged_no_rule",
                destination_status="unchanged_no_rule", destination_b64=""):
            return {"origin_station_raw": origin, "origin_station_clean": origin,
                    "origin_station_id": "", "origin_station_raw_base64": "",
                    "origin_station_repair_status": origin_status,
                    "destination_station_raw": destination, "destination_station_clean": destination,
                    "destination_station_id": "", "destination_station_raw_base64": destination_b64,
                    "destination_station_repair_status": destination_status}
        return pd.DataFrame([
            row("A", "B"), row("A", "B"), row("A old", "B"),
            row("A", "A"), row("A", "NTP", destination_status="not_an_error", destination_b64="TlRQ"),
            row("A", "B", origin_status="ambiguous"),
        ])

    def test_directed_weights_repeats_self_loop_cross_city_and_exclusion(self):
        edges, stats, labels = aggregate_frames([self.frame()], self.evidence, 2023, 1)
        weights = {(r.origin_station_id, r.destination_station_id): r.trip_count for r in edges.itertuples()}
        self.assertEqual(weights[("T1", "T2")], 3)
        self.assertEqual(weights[("T1", "T1")], 1)
        self.assertEqual(weights[("T1", "N1")], 1)
        self.assertEqual(stats["eligible_trip_count"], 5)
        self.assertEqual(stats["self_loop_trips"], 1)
        self.assertEqual(labels["T1"], {"A", "A old"})

    def test_station_id_not_label_defines_node_and_order_is_deterministic(self):
        edges, _, _ = aggregate_frames([self.frame()], self.evidence, 2023, 1)
        pairs = list(zip(edges.origin_station_id, edges.destination_station_id))
        self.assertEqual(pairs, sorted(pairs))
        self.assertEqual(len(edges[edges.origin_station_id.eq("T1")]), 3)

    def test_policy_gate_constant_and_period_boundaries(self):
        self.assertEqual(POLICY_VERSION, "od-inclusion-policy-v1")
        from aggregate_primary_od import MONTHS
        self.assertEqual(MONTHS[0], "2023/01"); self.assertEqual(MONTHS[23], "2024/12")
        self.assertEqual(MONTHS[-1], "2025/03"); self.assertEqual(len(MONTHS), 27)
        with self.assertRaisesRegex(RuntimeError, "policy version gate failed"):
            validate_policy({"policy_version": "unexpected-policy"})

    def test_combine_reads_hive_style_paths_without_partition_type_conflict(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "year=2023" / "month=01" / "od.parquet"
            edges = pd.DataFrame([{ "year": 2023, "month": 1, "origin_station_id": "T1",
                                    "destination_station_id": "T2", "origin_station_name": "A",
                                    "origin_city": "Taipei", "destination_station_name": "B",
                                    "destination_city": "Taipei", "trip_count": 2}])
            write_parquet(edges, path)
            combined = combine_edges([path])
            self.assertEqual(int(combined.trip_count.sum()), 2)

    def test_committed_manifest_and_exclusion_audit_conserve_all_periods(self):
        import json
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / "notes/od-aggregation-manifest.json").read_text(encoding="utf-8"))
        exclusion = json.loads((root / "notes/od-exclusion-audit.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["policy_version"], POLICY_VERSION)
        self.assertEqual(len(manifest["monthly"]), 27)
        self.assertTrue(all(row["eligible_trip_count"] > 0 and row["validation_status"] == "passed"
                            for row in manifest["monthly"]))
        self.assertEqual(sum(row["eligible_trip_count"] for row in manifest["monthly"][:24]),
                         manifest["core_eligible_trip_count"])
        self.assertEqual(sum(row["eligible_trip_count"] for row in manifest["monthly"]),
                         manifest["full_eligible_trip_count"])
        self.assertEqual(exclusion["eligible_records"] + exclusion["excluded_union"],
                         exclusion["total_input_records"])
        self.assertTrue(exclusion["conservation_passed"])

    def test_real_outputs_are_sorted_and_reconcile_with_receipts(self):
        import pyarrow.parquet as pq
        root = Path(__file__).resolve().parents[1]
        manifest = __import__("json").loads((root / "notes/od-aggregation-manifest.json").read_text(encoding="utf-8"))
        paths = [root / "data/processed/od/monthly/year=2023/month=01/od.parquet",
                 root / "data/processed/od/aggregate/full_2023_2025_03/od.parquet"]
        expected = [manifest["monthly"][0]["eligible_trip_count"], manifest["full_eligible_trip_count"]]
        for path, total in zip(paths, expected):
            frame = pq.ParquetFile(path).read().to_pandas()
            keys = list(zip(frame.origin_station_id, frame.destination_station_id))
            self.assertEqual(keys, sorted(keys))
            self.assertEqual(int(frame.trip_count.sum()), total)


if __name__ == "__main__": unittest.main()
