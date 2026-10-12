from pathlib import Path
import ast
import json
import sys
import unittest

import networkx as nx
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from run_core_louvain import (compare_partition, execute_louvain, modularity_contributions,
                              partition_fingerprint)
from validate_louvain_contract import deterministic_relabel, load_contract, project_od


class CoreLouvainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.contract = load_contract(cls.root / "config/louvain_contract.yaml")
        cls.frame = pd.DataFrame({
            "origin_station_id": ["A", "B", "A", "B", "C", "D", "E", "D", "F"],
            "destination_station_id": ["B", "A", "C", "C", "A", "E", "D", "F", "F"],
            "trip_count": [8, 7, 9, 8, 7, 8, 7, 1, 10],
        })

    def test_all_nodes_assigned_once_and_relabel_is_deterministic(self):
        graph = project_od(self.frame, "sum", True)
        result = execute_louvain(graph, self.contract, seed=42, resolution=1.0)
        self.assertEqual(set(result["labels"]), set(graph))
        self.assertEqual(len(result["labels"]), graph.number_of_nodes())
        shuffled = list(reversed(result["communities"]))
        self.assertEqual(deterministic_relabel(shuffled), result["labels"])

    def test_fixed_seed_fingerprint_reproducibility_and_seed_propagation(self):
        graph = project_od(self.frame, "sum", True)
        first = execute_louvain(graph, self.contract, seed=42, resolution=1.0)
        second = execute_louvain(graph, self.contract, seed=42, resolution=1.0)
        self.assertEqual(first["partition_fingerprint"], second["partition_fingerprint"])
        self.assertEqual(first["partition_fingerprint"], partition_fingerprint(first["labels"]))

    def test_manual_contributions_sum_to_modularity_and_resolution_propagates(self):
        graph = project_od(self.frame, "sum", True)
        for resolution in (0.5, 1.0, 1.5):
            result = execute_louvain(graph, self.contract, seed=42, resolution=resolution)
            contributions = modularity_contributions(graph, result["communities"], resolution)
            self.assertAlmostEqual(sum(item["modularity_contribution"] for item in contributions),
                                   result["modularity"], places=12)

    def test_primary_projection_removes_and_sensitivity_retains_loop(self):
        primary = project_od(self.frame, "sum", True)
        sensitivity = project_od(self.frame, "sum", False)
        self.assertEqual(nx.number_of_selfloops(primary), 0)
        self.assertEqual(nx.number_of_selfloops(sensitivity), 1)
        self.assertEqual(sensitivity["F"]["F"]["trip_count"], 10)

    def test_reciprocal_projection_matches_phase60_rule(self):
        graph = project_od(self.frame, "sum", True)
        self.assertEqual(graph["A"]["B"]["trip_count"], 15)
        self.assertEqual(graph["D"]["E"]["trip_count"], 15)

    def test_ari_nmi_identical_partition_equal_one(self):
        labels = {"A": 1, "B": 1, "C": 2}
        ari, nmi = compare_partition(labels, dict(labels))
        self.assertAlmostEqual(ari, 1.0)
        self.assertAlmostEqual(nmi, 1.0)

    def test_committed_assignment_and_sensitivity_schema(self):
        receipt = json.loads((self.root / "notes/louvain-run-receipt.json").read_text(encoding="utf-8"))
        sensitivity = json.loads((self.root / "notes/louvain-sensitivity-summary.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["node_count"], 2782)
        self.assertTrue(all(receipt["validation"].values()))
        required = {"variant", "projection", "self_loop_mode", "resolution", "seed", "weighted",
                    "community_count", "modularity", "ari_vs_primary", "nmi_vs_primary", "runtime_seconds"}
        self.assertTrue(all(required.issubset(item) for item in sensitivity["variants"]))

    def test_no_kmeans_or_hierarchical_execution_in_runner(self):
        tree = ast.parse((self.root / "src/run_core_louvain.py").read_text(encoding="utf-8"))
        calls = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        self.assertFalse({"fit", "fit_predict", "linkage", "fcluster"} & calls)


if __name__ == "__main__":
    unittest.main()
