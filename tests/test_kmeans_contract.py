from pathlib import Path
import json
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from validate_kmeans_contract import (FEATURES, bounded_real_validation, deterministic_relabel,
                                      extract_features, geometric_knee, load_contract, make_kmeans,
                                      synthetic_validation)


class KMeansContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.contract = load_contract(cls.root / "config/kmeans_contract.yaml")
        cls.frame = pd.DataFrame({"station_id": [f"S{i}" for i in range(8)],
                                  "total_strength": [1, 2, 3, 4, 100, 110, 120, 1000],
                                  "betweenness_primary": [0, .01, .02, .03, .2, .21, .22, .8],
                                  "clustering_primary": [.9, .8, .85, .82, .4, .42, .38, .1],
                                  "pagerank_primary": [.001, .002, .003, .004, .02, .021, .022, .08],
                                  "community_id": [1] * 8, "latitude": [25.0] * 8})

    def test_feature_extraction_exact_no_leakage_and_node_count(self):
        changed = json.loads(json.dumps(self.contract)); changed["input"]["expected_node_count"] = 8
        stations, matrix = extract_features(self.frame, changed)
        self.assertEqual(matrix.columns.tolist(), FEATURES)
        self.assertNotIn("community_id", matrix)
        self.assertNotIn("latitude", matrix)
        self.assertEqual(len(stations), 8)

    def test_nan_inf_fail_closed(self):
        changed = json.loads(json.dumps(self.contract)); changed["input"]["expected_node_count"] = 8
        for value in (np.nan, np.inf):
            frame = self.frame.copy(); frame.loc[0, "pagerank_primary"] = value
            with self.assertRaisesRegex(ValueError, "NaN or infinite"):
                extract_features(frame, changed)

    def test_standard_scaler_and_inverse_transform(self):
        scaled = StandardScaler().fit_transform(self.frame[FEATURES])
        scaler = StandardScaler().fit(self.frame[FEATURES])
        self.assertTrue(np.allclose(scaled.mean(axis=0), 0, atol=1e-12))
        self.assertTrue(np.allclose(scaled.var(axis=0), 1, atol=1e-12))
        self.assertTrue(np.allclose(scaler.inverse_transform(scaled), self.frame[FEATURES]))

    def test_kmeans_parameters_determinism_n_init_and_inertia(self):
        scaled = StandardScaler().fit_transform(self.frame[FEATURES])
        first = make_kmeans(self.contract, 3).fit(scaled)
        second = make_kmeans(self.contract, 3).fit(scaled)
        self.assertEqual(first.n_init, 50)
        self.assertTrue(np.array_equal(first.labels_, second.labels_))
        self.assertAlmostEqual(first.inertia_, second.inertia_)

    def test_k_range_and_geometric_knee(self):
        self.assertEqual(self.contract["elbow"]["k_values"], list(range(1, 11)))
        result = geometric_knee([1, 2, 3, 4, 5], [100, 55, 32, 26, 23])
        self.assertIn(result["selected_k"], range(1, 6))

    def test_relabel_deterministic_and_not_semantic(self):
        stations = ["B", "A", "D", "C"]
        first = deterministic_relabel([9, 9, 2, 2], stations)
        second = deterministic_relabel([3, 3, 7, 7], stations)
        self.assertTrue(np.array_equal(first, second))
        self.assertFalse(self.contract["labels"]["semantic_order"])

    def test_outlier_retained_in_synthetic(self):
        result = synthetic_validation(self.contract)
        self.assertTrue(result["checks"]["all_rows_retained"])
        self.assertTrue(result["checks"]["extreme_value_retained"])

    def test_unknown_scaler_fails_closed(self):
        changed = json.loads(json.dumps(self.contract)); changed["preprocessing"]["primary_scaler"] = "mystery"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"; path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown scaler"):
                load_contract(path)

    def test_committed_validation_has_no_full_core_kmeans(self):
        evidence = json.loads((self.root / "notes/kmeans-contract-validation.json").read_text(encoding="utf-8"))
        self.assertFalse(evidence["full_core_kmeans_executed"])
        self.assertEqual(evidence["node_count"], 2782)
        self.assertEqual(evidence["selected_features"], FEATURES)


if __name__ == "__main__":
    unittest.main()
