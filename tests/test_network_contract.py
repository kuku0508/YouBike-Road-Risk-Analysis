from pathlib import Path
import json
import sys
import tempfile
import unittest

import networkx as nx
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from validate_network_contract import (add_distance_transforms, graph_from_od, load_contract,
                                       synthetic_graph, validate_synthetic, weighted_strength,
                                       without_self_loops)


class NetworkContractTests(unittest.TestCase):
    def test_od_to_directed_graph_preserves_counts_weights_and_loop(self):
        frame = pd.DataFrame({"origin_station_id": ["A", "A", "B"],
                              "destination_station_id": ["B", "A", "C"],
                              "trip_count": [4, 3, 2]})
        graph = graph_from_od(frame)
        self.assertTrue(graph.is_directed()); self.assertFalse(graph.is_multigraph())
        self.assertEqual(graph.number_of_nodes(), 3); self.assertEqual(graph.number_of_edges(), 3)
        self.assertEqual(graph.size(weight="trip_count"), 9)
        self.assertEqual(nx.number_of_selfloops(graph), 1)

    def test_duplicate_od_edge_and_invalid_flow_fail_closed(self):
        duplicate = pd.DataFrame({"origin_station_id": ["A", "A"],
                                  "destination_station_id": ["B", "B"], "trip_count": [1, 2]})
        with self.assertRaisesRegex(ValueError, "duplicate OD edge"): graph_from_od(duplicate)
        invalid = pd.DataFrame({"origin_station_id": ["A"], "destination_station_id": ["B"],
                                "trip_count": [0]})
        with self.assertRaisesRegex(ValueError, "nonpositive flow"): graph_from_od(invalid)

    def test_weighted_strength_counts_self_loop_in_and_out(self):
        self.assertEqual(weighted_strength(synthetic_graph(), "D"),
                         {"in_strength": 9.0, "out_strength": 6.0, "total_strength": 15.0})

    def test_directed_shortest_path_and_inverse_flow_transform(self):
        graph = add_distance_transforms(without_self_loops(synthetic_graph()))
        self.assertEqual(nx.shortest_path(graph, "A", "B"), ["A", "B"])
        self.assertEqual(nx.shortest_path(graph, "A", "B", weight="inverse_flow_distance"),
                         ["A", "C", "B"])

    def test_eigenvector_pagerank_and_clustering_semantics(self):
        result = validate_synthetic()
        self.assertNotEqual(result["eigenvector_left_predecessor"], result["eigenvector_right_via_reverse"])
        self.assertAlmostEqual(result["pagerank_weighted_sum"], 1.0)
        self.assertNotEqual(result["pagerank_weighted"], result["pagerank_unweighted"])
        self.assertEqual(result["clustering_formula_probe"]["y"], 1.0)
        self.assertAlmostEqual(result["clustering_formula_probe"]["x"], 1 / 3)

    def test_contract_parses_and_unknown_options_fail_closed(self):
        root = Path(__file__).resolve().parents[1]
        contract = load_contract(root / "config/network_metric_contract.yaml")
        self.assertEqual(contract["contract_version"], "network-metric-contract-v1")
        bad = dict(contract); bad["contract_version"] = "unknown"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bad.json"; path.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown contract version"): load_contract(path)

    def test_committed_core_validation_matches_phase41(self):
        root = Path(__file__).resolve().parents[1]
        evidence = json.loads((root / "notes/network-construction-validation.json").read_text(encoding="utf-8"))
        observed = evidence["core_graph_integrity"]["observed"]
        self.assertEqual(observed["node_count"], 2782)
        self.assertEqual(observed["edge_count"], 1125519)
        self.assertEqual(observed["weight_sum"], 91138763)
        self.assertEqual(observed["self_loop_edges"], 1504)
        self.assertEqual(observed["self_loop_trips"], 6023568)
        self.assertFalse(evidence["scope_guard"]["full_core_centrality_computed"])


if __name__ == "__main__": unittest.main()
