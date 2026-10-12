from collections import Counter
import ast
from pathlib import Path
import sys
import tempfile
import unittest

import networkx as nx
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from reconstruct_hourly_sna_features import (DAY_TYPES, METRICS, checkpoint_metric,
    compute_bucket, counter_to_edges, exact_directed_betweenness_igraph, extract_hour, graph_fingerprint, load_calendar,
    load_contract)


class HourlySnaFeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.contract = load_contract(cls.root / "config/hourly_sna_feature_contract.yaml")

    def test_contract_period_and_exact_feature_set(self):
        self.assertEqual(self.contract["analysis_period"], "2023-01-01/2024-12-31")
        self.assertEqual(self.contract["features"]["metrics"], list(METRICS))
        self.assertEqual(self.contract["features"]["hours"], list(range(24)))
        self.assertEqual(self.contract["features"]["feature_count"], 72)
        self.assertEqual(self.contract["features"]["scaling"], "none_in_phase_7_3")
        self.assertTrue((self.root / "notes/station-universe-classification.csv").exists())

    def test_calendar_schema_hash_coverage_uniqueness_and_mapping(self):
        frame, audit = load_calendar(self.root / "data/raw/2020_2025假日.fst",
            self.contract["calendar"]["sha256"], Path(r"C:\Program Files\R\R-4.5.2\bin\Rscript.exe"),
            self.root / "src/export_fst_calendar.R")
        self.assertEqual(list(frame.columns), ["Date", "IsHoliday", "NaturalDisaster"])
        self.assertEqual(len(frame), 731)
        self.assertFalse(frame.Date.duplicated().any())
        self.assertEqual(set(frame.IsHoliday), {0, 1})
        self.assertEqual(audit["missing_dates"], [])
        self.assertEqual(audit["source_sha256"], self.contract["calendar"]["sha256"])

    def test_calendar_hash_gate(self):
        with self.assertRaises(RuntimeError):
            load_calendar(self.root / "data/raw/2020_2025假日.fst", "0" * 64,
                Path(r"C:\Program Files\R\R-4.5.2\bin\Rscript.exe"), self.root / "src/export_fst_calendar.R")

    def test_natural_disaster_does_not_override(self):
        self.assertFalse(self.contract["calendar"]["natural_disaster_changes_day_type"])

    def test_hour_extraction(self):
        self.assertEqual(extract_hour(pd.Series(["00", "7", "23", "08:00", "2023-01-27 15:00:00"])).tolist(), [0, 7, 23, 8, 15])
        with self.assertRaises(RuntimeError): extract_hour(pd.Series(["24"]))
        with self.assertRaises(RuntimeError): extract_hour(pd.Series(["bad"]))

    def test_48_buckets_and_repeated_records_preserved(self):
        buckets = {(day, hour): Counter() for day in DAY_TYPES for hour in range(24)}
        self.assertEqual(len(buckets), 48)
        buckets[("weekday", 8)].update({("A", "B"): 2})
        self.assertEqual(counter_to_edges(buckets[("weekday", 8)]).trip_count.sum(), 2)

    def test_fixed_station_universe_and_metric_parameters(self):
        self.assertEqual(self.contract["station_universe"]["expected_node_count"], 2782)
        self.assertTrue(self.contract["station_universe"]["fixed_across_all_48_buckets"])
        self.assertTrue(self.contract["metrics"]["betweenness"]["exact"])
        self.assertEqual(self.contract["metrics"]["betweenness"]["backend"], "python-igraph")
        self.assertIsNone(self.contract["metrics"]["betweenness"]["weight"])
        self.assertEqual(self.contract["metrics"]["eigenvector"]["semantics"], "left_predecessor")
        self.assertEqual(self.contract["metrics"]["pagerank"]["alpha"], 0.85)

    def test_small_metric_execution_numerical_gates(self):
        nodes = ["A", "B", "C"] + [f"I{i:04d}" for i in range(2779)]
        edges = pd.DataFrame({"origin_station_id": ["A", "B", "C", "A"],
                              "destination_station_id": ["B", "C", "A", "A"],
                              "trip_count": [3, 2, 1, 4]})
        with tempfile.TemporaryDirectory() as folder:
            metrics, receipt = compute_bucket("weekday", 8, edges, nodes, Path(folder),
                                              {"test": "identity"}, 1)
        self.assertEqual(metrics.station_id.tolist(), nodes)
        self.assertTrue(np.isfinite(metrics[list(METRICS)]).all().all())
        self.assertAlmostEqual(metrics.pagerank.sum(), 1.0)
        self.assertEqual(metrics.loc[metrics.station_id.eq("I0000"), "eigenvector"].item(), 0.0)
        self.assertEqual(receipt["validation_status"], "passed")

    def test_eigenvector_nonconvergence_fails_closed(self):
        graph = nx.path_graph(5, create_using=nx.DiGraph)
        with self.assertRaises(nx.PowerIterationFailedConvergence):
            nx.eigenvector_centrality(graph, max_iter=0, tol=1e-9)

    def test_exact_igraph_betweenness_matches_networkx(self):
        nodes = ["A", "B", "C", "D", "E"]
        edges = pd.DataFrame({"origin_station_id": ["A", "A", "B", "C", "D", "E", "A"],
                              "destination_station_id": ["B", "C", "D", "D", "E", "A", "A"],
                              "trip_count": [2, 1, 1, 3, 1, 1, 9]})
        graph = nx.DiGraph(); graph.add_nodes_from(nodes)
        graph.add_edges_from((u, v) for u, v in zip(edges.origin_station_id, edges.destination_station_id) if u != v)
        expected = nx.betweenness_centrality(graph, normalized=True, weight=None, endpoints=False)
        observed = exact_directed_betweenness_igraph(edges, nodes)
        self.assertTrue(np.allclose([expected[n] for n in nodes], [observed[n] for n in nodes], atol=1e-15))

    def test_checkpoint_identity_gate(self):
        nodes = ["A", "B"]
        with tempfile.TemporaryDirectory() as folder:
            calls = {"n": 0}
            def first(): calls["n"] += 1; return {"A": 0.2, "B": 0.8}
            checkpoint_metric("metric", nodes, Path(folder), {"version": "one"}, first)
            checkpoint_metric("metric", nodes, Path(folder), {"version": "one"}, first)
            self.assertEqual(calls["n"], 1)
            checkpoint_metric("metric", nodes, Path(folder), {"version": "two"}, first)
            self.assertEqual(calls["n"], 2)

    def test_deterministic_graph_fingerprint(self):
        edges = counter_to_edges(Counter({("B", "A"): 2, ("A", "B"): 1}))
        self.assertEqual(graph_fingerprint(edges, ["A", "B"]), graph_fingerprint(edges.copy(), ["A", "B"]))

    def test_no_feature_leakage_or_hierarchical_execution(self):
        forbidden_features = {"weighted_degree", "clustering", "louvain", "coordinates", "city", "district"}
        self.assertFalse(forbidden_features & set(self.contract["features"]["metrics"]))
        tree = ast.parse((self.root / "src/reconstruct_hourly_sna_features.py").read_text(encoding="utf-8"))
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
                    for alias in node.names}
        self.assertFalse(any("cluster" in name.lower() for name in imported))

    def test_completed_manifest_and_matrices(self):
        manifest = __import__("json").loads((self.root / "notes/hourly-sna-feature-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "complete")
        self.assertEqual(manifest["bucket_count"], 48)
        self.assertEqual(manifest["conservation"]["total_eligible_trips"], 91_138_763)
        self.assertTrue(manifest["conservation"]["bucket_sum_equals_expected"])
        self.assertTrue(manifest["exact_betweenness"])
        self.assertFalse(manifest["hierarchical_clustering_executed"])
        self.assertGreater(manifest["initial_full_execution_runtime_seconds"],
                           manifest["latest_invocation_runtime_seconds"])
        self.assertTrue(all(item["validation_status"] == "passed" and all(item["validation"].values())
                            for item in manifest["buckets"]))
        for day_type in DAY_TYPES:
            matrix = manifest["matrices"][day_type]
            self.assertEqual(matrix["shape"], [2782, 72])
            self.assertTrue(matrix["no_nan"] and matrix["all_finite"])
            self.assertFalse(matrix["scaling_applied"])


if __name__ == "__main__": unittest.main()
