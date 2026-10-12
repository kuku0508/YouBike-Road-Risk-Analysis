from pathlib import Path
import json
import sys
import unittest

import networkx as nx
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from run_core_sna_metrics import deterministic_rank, sensitivity_summary, validate_metrics
from validate_network_contract import add_distance_transforms, graph_from_od, without_self_loops


class CoreSNAMetricTests(unittest.TestCase):
    def test_strength_loop_and_flow_conservation(self):
        frame = pd.DataFrame({"origin_station_id": ["A", "A", "B"],
                              "destination_station_id": ["A", "B", "A"], "trip_count": [3, 4, 2]})
        graph = graph_from_od(frame)
        self.assertEqual(sum(dict(graph.in_degree(weight="trip_count")).values()), 9)
        self.assertEqual(sum(dict(graph.out_degree(weight="trip_count")).values()), 9)
        self.assertEqual(graph.in_degree("A", weight="trip_count"), 5)
        self.assertEqual(graph.out_degree("A", weight="trip_count"), 7)

    def test_betweenness_excludes_loop_and_transforms_are_exact(self):
        frame = pd.DataFrame({"origin_station_id": ["A", "A", "A", "C"],
                              "destination_station_id": ["A", "B", "C", "B"],
                              "trip_count": [5, 1, 10, 10]})
        graph = add_distance_transforms(without_self_loops(graph_from_od(frame)))
        self.assertEqual(nx.number_of_selfloops(graph), 0)
        self.assertAlmostEqual(graph["A"]["C"]["inverse_flow_distance"], 0.1)
        self.assertAlmostEqual(graph["A"]["C"]["inverse_log_flow_distance"], 1 / __import__("math").log1p(10))

    def test_deterministic_ranking_tie_break_and_spearman(self):
        frame = pd.DataFrame({"station_id": ["B", "A", "C"], "station_name": ["b", "a", "c"],
                              "city": ["x"] * 3, "metric": [2.0, 2.0, 1.0],
                              "primary": [3.0, 2.0, 1.0], "variant": [3.0, 2.0, 1.0]})
        ranked = deterministic_rank(frame, "metric")
        self.assertEqual(ranked.station_id.tolist(), ["A", "B", "C"])
        from run_core_sna_metrics import SENSITIVITY_PAIRS
        original = list(SENSITIVITY_PAIRS)
        try:
            SENSITIVITY_PAIRS[:] = [("primary", "variant")]
            summary = sensitivity_summary(frame)
            self.assertAlmostEqual(summary[0]["spearman_rank_correlation"], 1.0)
        finally: SENSITIVITY_PAIRS[:] = original

    def test_committed_metrics_numerical_contract(self):
        root = Path(__file__).resolve().parents[1]
        receipt = json.loads((root / "notes/sna-metrics-receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["node_count"], 2782)
        self.assertTrue(all(receipt["validation"].values()))
        self.assertEqual(receipt["convergence_status"], "all_converged")


if __name__ == "__main__": unittest.main()
