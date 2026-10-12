from pathlib import Path
import ast
import json
import sys
import unittest

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from run_core_kmeans import (assignment_fingerprint, compare_labels, fit_kmeans,
                             relabel_fit, scaling_matrix, validate_metrics)
from validate_kmeans_contract import geometric_knee, load_contract, sha256_file


class CoreKMeansTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.contract = load_contract(cls.root / "config/kmeans_contract.yaml")
        cls.metrics_path = cls.root / "data/processed/network/core_2023_2024/node_metrics.parquet"
        cls.receipt = json.loads((cls.root / "notes/kmeans-run-receipt.json").read_text(encoding="utf-8"))
        cls.primary = json.loads((cls.root / "notes/kmeans-primary-summary.json").read_text(encoding="utf-8"))
        cls.sensitivity = json.loads((cls.root / "notes/kmeans-sensitivity-summary.json").read_text(encoding="utf-8"))
        cls.elbow = pd.read_csv(cls.root / "notes/kmeans-elbow.csv")

    def test_full_matrix_exact_features_no_leakage_source_gate(self):
        metrics = pq.ParquetFile(self.metrics_path).read().to_pandas()
        frame, matrix = validate_metrics(metrics, self.contract, self.metrics_path)
        self.assertEqual(matrix.shape, (2782, 4))
        self.assertEqual(self.contract["features"], ["total_strength", "betweenness_primary",
                                                    "clustering_primary", "pagerank_primary"])
        self.assertEqual(sha256_file(self.metrics_path), self.contract["input"]["sha256"])
        self.assertFalse({"community_id", "city", "station_name"} & set(self.contract["features"]))
        self.assertTrue(np.isfinite(matrix).all())
        self.assertEqual(len(frame), 2782)

    def test_scaler_is_full_core_and_no_outlier_removal(self):
        self.assertEqual(self.primary["node_count"], 2782)
        self.assertEqual(self.receipt["scaler"], "StandardScaler")
        self.assertTrue(self.receipt["validation"]["outliers_retained"])
        self.assertEqual(set(self.receipt["scaler_parameters"]["mean"]), set(self.contract["features"]))

    def test_elbow_and_silhouette_ranges_complete(self):
        self.assertEqual(self.elbow.k.tolist(), list(range(1, 11)))
        self.assertTrue(self.elbow.loc[self.elbow.k >= 2, "silhouette"].notna().all())
        self.assertTrue(pd.isna(self.elbow.loc[self.elbow.k == 1, "silhouette"].iloc[0]))
        knee = geometric_knee(self.elbow.k.astype(int).tolist(), self.elbow.inertia.astype(float).tolist())
        self.assertEqual(int(knee["selected_k"]), self.receipt["detected_knee"])
        expected_distances = [knee["distances"][str(k)] for k in range(1, 11)]
        self.assertTrue(np.allclose(expected_distances, self.elbow.distance_to_chord))

    def test_k4_all_nodes_relabel_centroids_and_inverse(self):
        partition = pq.ParquetFile(self.root / "data/processed/network/core_2023_2024/kmeans_k4_partition.parquet").read().to_pandas()
        summary = pq.ParquetFile(self.root / "data/processed/network/core_2023_2024/kmeans_k4_summary.parquet").read().to_pandas()
        self.assertEqual(len(partition), 2782)
        self.assertTrue(partition.station_id.is_unique)
        self.assertEqual(sorted(partition.cluster_id.unique()), [1, 2, 3, 4])
        self.assertEqual(len(summary), 4)
        self.assertTrue(self.receipt["validation"]["centroid_inverse_transform"])

    def test_primary_reproducibility_and_deterministic_relabel(self):
        self.assertTrue(self.primary["fixed_seed_reproducible"])
        self.assertEqual(self.primary["assignment_fingerprint"], self.primary["repeat_assignment_fingerprint"])
        self.assertEqual(self.primary["assignment_fingerprint"], self.receipt["assignment_fingerprint"])

    def test_seed_stability_metrics_complete(self):
        variants = [item for item in self.sensitivity["variants"] if item["variant_type"] == "seed"]
        self.assertEqual([item["seed"] for item in variants], [42, 7, 19, 73])
        self.assertTrue(all(0 <= item["ari_vs_primary"] <= 1 for item in variants))
        self.assertTrue(all(0 <= item["nmi_vs_primary"] <= 1 for item in variants))
        self.assertTrue(all(sum(x["node_count"] for x in item["cluster_sizes"]) == 2782 for item in variants))

    def test_scaling_sensitivity_metrics_complete(self):
        variants = [item for item in self.sensitivity["variants"] if item["variant_type"] == "scaling"]
        expected = self.contract["sensitivity_variants"]["scaling"]
        self.assertEqual([item["variant"] for item in variants], expected)
        self.assertTrue(all(not item["inertia_cross_scaler_comparable"] for item in variants))
        sample = np.array([[1.0, 2.0, 0.1, 0.01], [100.0, 4.0, 0.8, 0.02]])
        self.assertTrue(np.array_equal(scaling_matrix(sample, "none"), sample))

    def test_helpers_membership_metrics_and_hash(self):
        labels = np.array([1, 1, 2, 2])
        ari, nmi = compare_labels(labels, labels.copy())
        self.assertAlmostEqual(ari, 1.0)
        self.assertAlmostEqual(nmi, 1.0)
        self.assertEqual(assignment_fingerprint(["B", "A"], np.array([2, 1])),
                         assignment_fingerprint(["A", "B"], np.array([1, 2])))

    def test_no_hierarchical_clustering_triggered(self):
        tree = ast.parse((self.root / "src/run_core_kmeans.py").read_text(encoding="utf-8"))
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        self.assertFalse({"linkage", "fcluster", "AgglomerativeClustering"} & (names | attributes))
        self.assertTrue(self.receipt["validation"]["no_hierarchical_clustering"])


if __name__ == "__main__":
    unittest.main()
