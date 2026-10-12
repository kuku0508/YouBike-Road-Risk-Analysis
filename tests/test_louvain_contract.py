from pathlib import Path
import json
import sys
import tempfile
import unittest

import networkx as nx
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from validate_louvain_contract import (deterministic_relabel, load_contract,
                                       manual_weighted_modularity, project_od,
                                       synthetic_validation)


class LouvainContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.contract = load_contract(cls.root / "config/louvain_contract.yaml")
        cls.frame = pd.DataFrame({
            "origin_station_id": ["A", "B", "A", "C", "D"],
            "destination_station_id": ["B", "A", "C", "C", "D"],
            "trip_count": [3, 4, 5, 7, 11],
        })

    def test_reciprocal_sum_one_way_no_duplicates_and_conservation(self):
        graph = project_od(self.frame, "sum", True)
        self.assertEqual(graph["A"]["B"]["trip_count"], 7)
        self.assertEqual(graph["A"]["C"]["trip_count"], 5)
        self.assertEqual(graph.number_of_edges(), 2)
        self.assertEqual(int(graph.size(weight="trip_count")), 12)
        self.assertEqual(int(graph.size(weight="trip_count")) + 18, int(self.frame.trip_count.sum()))

    def test_self_loop_and_isolate_policy(self):
        graph = project_od(self.frame, "sum", True)
        self.assertEqual(nx.number_of_selfloops(graph), 0)
        self.assertEqual(set(nx.isolates(graph)), {"D"})

    def test_modularity_matches_independent_formula_and_resolution_propagates(self):
        graph = project_od(self.frame.iloc[:3], "sum", True)
        communities = [{"A", "B"}, {"C"}]
        for resolution in (0.5, 1.0, 1.5):
            expected = nx.community.modularity(graph, communities, weight="trip_count", resolution=resolution)
            self.assertAlmostEqual(manual_weighted_modularity(graph, communities, resolution), expected)

    def test_fixed_seed_synthetic_partition_is_deterministic(self):
        validation = synthetic_validation(self.contract)
        self.assertTrue(validation["checks"]["fixed_seed_deterministic"])
        self.assertTrue(validation["checks"]["isolated_in_louvain_partition"])

    def test_deterministic_relabel(self):
        first = deterministic_relabel([{"C", "D"}, {"A", "B"}])
        second = deterministic_relabel([{"B", "A"}, {"D", "C"}])
        self.assertEqual(first, second)
        self.assertEqual(first, {"A": 1, "B": 1, "C": 2, "D": 2})

    def test_contract_version_library_and_phase_guard(self):
        algorithm = self.contract["algorithm"]
        self.assertEqual(algorithm["library_version"], nx.__version__)
        self.assertEqual(algorithm["function"], "networkx.algorithms.community.louvain_communities")
        self.assertFalse(self.contract["phase_6_0_guard"]["full_core_louvain_allowed"])

    def test_unknown_projection_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "unknown projection"):
            project_od(self.frame, "not-a-mode", True)

    def test_unknown_contract_projection_fails_closed(self):
        changed = json.loads(json.dumps(self.contract))
        changed["target_graph"]["projection_mode"] = "not-a-mode"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown projection"):
                load_contract(path)

    def test_committed_validation_did_not_run_core_louvain(self):
        evidence = json.loads((self.root / "notes/louvain-contract-validation.json").read_text(encoding="utf-8"))
        self.assertFalse(evidence["full_core_louvain_executed"])
        self.assertEqual(evidence["validation_status"], "passed")


if __name__ == "__main__":
    unittest.main()
