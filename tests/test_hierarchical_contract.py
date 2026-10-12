from pathlib import Path
import ast
import json
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from validate_hierarchical_contract import (assert_execution_ready, deterministic_relabel,
                                            execute_hierarchy, expected_feature_columns,
                                            load_contract, prepare_matrix, synthetic_validation)


class HierarchicalContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.contract = load_contract(cls.root / "config/hierarchical_clustering_contract.yaml")
        cls.validation = json.loads((cls.root / "notes/hierarchical-contract-validation.json").read_text(encoding="utf-8"))

    def test_contract_period_features_and_no_leakage(self):
        self.assertEqual(self.contract["period_resolution"], "clearly_2022_2024")
        self.assertEqual(self.contract["analysis_units"], ["weekday", "holiday"])
        self.assertEqual(self.contract["features"]["metrics"], ["betweenness", "eigenvector", "pagerank"])
        self.assertEqual(len(expected_feature_columns()), 72)
        self.assertFalse(self.contract["features"]["weighted_degree_included"])
        self.assertFalse(self.contract["features"]["clustering_coefficient_included"])

    def test_scaler_distance_linkage_and_cut_propagation(self):
        self.assertEqual(self.contract["preprocessing"]["primary_scaler"], "StandardScaler")
        self.assertEqual(self.contract["distance"]["metric"], "euclidean")
        self.assertEqual(self.contract["linkage"]["report_method"], "Ward.D2")
        self.assertEqual(self.contract["linkage"]["reconstruction_method"], "ward")
        self.assertEqual(self.contract["cut_rule"]["weekday_cluster_count"], 5)
        self.assertEqual(self.contract["cut_rule"]["holiday_cluster_count"], 4)

    def test_prepare_matrix_orders_and_rejects_nan_inf_leakage(self):
        frame = pd.DataFrame({"station_id": ["B", "A"], "betweenness": [1.0, 2.0],
                              "eigenvector": [3.0, 4.0], "pagerank": [5.0, 6.0]})
        stations, matrix = prepare_matrix(frame, exact_features=["betweenness", "eigenvector", "pagerank"])
        self.assertEqual(stations, ["A", "B"])
        self.assertEqual(matrix.shape, (2, 3))
        with self.assertRaises(ValueError):
            prepare_matrix(frame.assign(extra=1), exact_features=["betweenness", "eigenvector", "pagerank"])
        with self.assertRaises(ValueError):
            prepare_matrix(frame.assign(pagerank=[np.nan, 1.0]), exact_features=["betweenness", "eigenvector", "pagerank"])

    def test_linkage_and_labels_are_deterministic_outlier_retained(self):
        stations = [f"S{i}" for i in range(8)]
        matrix = np.array([[i, i * 2, i / 10] for i in range(7)] + [[1000, 2000, 100]], dtype=float)
        first = execute_hierarchy(stations, matrix, method="ward", k=3)
        second = execute_hierarchy(stations, matrix, method="ward", k=3)
        self.assertEqual(first["linkage_sha256"], second["linkage_sha256"])
        self.assertEqual(first["assignment_sha256"], second["assignment_sha256"])
        self.assertEqual(len(first["labels"]), 8)
        self.assertEqual(first["linkage"].shape, (7, 4))

    def test_deterministic_relabel(self):
        labels = deterministic_relabel([9, 9, 3, 3], ["B", "A", "D", "C"])
        self.assertEqual(labels.tolist(), [1, 1, 2, 2])

    def test_unknown_linkage_fails_closed(self):
        with self.assertRaises(ValueError):
            execute_hierarchy(["A", "B"], np.array([[0.0], [1.0]]), method="single", k=2)

    def test_missing_required_period_input_fails_closed(self):
        with self.assertRaises(RuntimeError):
            assert_execution_ready(self.contract, self.root)
        self.assertFalse(self.validation["target_inputs_exist"])

    def test_synthetic_and_bounded_validations(self):
        result = synthetic_validation()
        self.assertTrue(all(result["checks"].values()))
        bounded = self.validation["bounded_real_validation"]
        self.assertEqual(bounded["row_count"], 12)
        self.assertTrue(bounded["deterministic"])

    def test_committed_guard_and_no_full_execution(self):
        self.assertFalse(self.validation["full_core_hierarchical_executed"])
        self.assertEqual(self.validation["blocked_reason"], "2022_NETWORK_RECONSTRUCTION_REQUIRED")
        tree = ast.parse((self.root / "src/validate_hierarchical_contract.py").read_text(encoding="utf-8"))
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
        self.assertFalse(any(isinstance(node.func, ast.Name) and node.func.id == "assert_execution_ready" for node in calls))


if __name__ == "__main__":
    unittest.main()
