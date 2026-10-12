from pathlib import Path
import ast
import json
import sys
import unittest

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.cluster.hierarchy import fcluster, leaves_list, linkage
from scipy.spatial.distance import pdist
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from run_hierarchical_reconstruction import (CUTS, INPUT_HASHES, load_input, relabel,
                                              validate_linkage)


class HierarchicalReconstructionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.base = cls.root / "data/processed/network/hourly_2023_2024"
        cls.receipt = json.loads((cls.root / "notes/hierarchical-run-receipt.json").read_text(encoding="utf-8"))
        cls.frames = {}; cls.matrices = {}; cls.features = {}
        for day in ("weekday", "holiday"):
            frame, features, matrix, evidence = load_input(cls.base / f"hierarchical_{day}_72_features.parquet", day)
            cls.frames[day] = frame; cls.features[day] = features; cls.matrices[day] = matrix

    def test_input_hash_gates(self):
        for day in ("weekday", "holiday"):
            self.assertEqual(self.receipt["primary"][day]["input_sha256"], INPUT_HASHES[day])

    def test_exact_72_features_and_no_leakage(self):
        self.assertEqual(self.features["weekday"], self.features["holiday"])
        self.assertEqual(len(self.features["weekday"]), 72)
        self.assertFalse({"city", "station_name", "weighted_degree", "clustering"} & set(self.features["weekday"]))

    def test_station_universe_order_unique_and_identical(self):
        for frame in self.frames.values():
            self.assertEqual(len(frame), 2782); self.assertTrue(frame.station_id.is_unique)
            self.assertEqual(frame.station_id.tolist(), sorted(frame.station_id.tolist()))
        self.assertEqual(self.frames["weekday"].station_id.tolist(), self.frames["holiday"].station_id.tolist())

    def test_no_nan_inf_or_outlier_removal(self):
        for matrix in self.matrices.values(): self.assertTrue(np.isfinite(matrix).all())
        for day in ("weekday", "holiday"):
            self.assertEqual(sum(self.receipt["primary"][day]["cluster_sizes"].values()), 2782)

    def test_independent_scalers(self):
        weekday = StandardScaler().fit(self.matrices["weekday"])
        holiday = StandardScaler().fit(self.matrices["holiday"])
        self.assertFalse(np.array_equal(weekday.mean_, holiday.mean_))
        self.assertNotEqual(self.receipt["primary"]["weekday"]["scaler"]["parameters_sha256"],
                            self.receipt["primary"]["holiday"]["scaler"]["parameters_sha256"])

    def test_primary_ward_euclidean_and_linkage_validation(self):
        for day in ("weekday", "holiday"):
            item = self.receipt["primary"][day]
            self.assertEqual(item["distance"], "euclidean"); self.assertEqual(item["linkage"], "ward")
            z = np.load(self.base / f"hierarchical_{day}_linkage.npy", allow_pickle=False)
            self.assertTrue(all(validate_linkage(z, 2782).values()))
            self.assertEqual(z.shape, (2781, 4)); self.assertTrue(np.all(np.diff(z[:, 2]) >= -1e-12))

    def test_report_reference_assignments(self):
        for day, k in CUTS.items():
            part = pq.ParquetFile(self.base / f"hierarchical_{day}_partition.parquet").read().to_pandas()
            labels = part[f"{day}_cluster_id"]
            self.assertEqual(len(part), 2782); self.assertTrue(part.station_id.is_unique)
            self.assertEqual(sorted(labels.unique()), list(range(1, k + 1)))

    def test_deterministic_relabel(self):
        self.assertEqual(relabel(np.array([9, 9, 3, 3]), ["B", "A", "D", "C"]).tolist(), [1, 1, 2, 2])

    def test_leaf_coverage_and_cophenetic(self):
        for day in ("weekday", "holiday"):
            leaf = json.loads((self.base / f"hierarchical_{day}_leaf_order.json").read_text(encoding="utf-8"))["station_ids"]
            self.assertEqual(len(leaf), 2782); self.assertEqual(set(leaf), set(self.frames[day].station_id))
            self.assertTrue(math_isfinite(self.receipt["primary"][day]["cophenetic_correlation"]))

    def test_sensitivity_variants_and_scores(self):
        for day in ("weekday", "holiday"):
            variants = {item["variant"]: item for item in self.receipt["primary"][day]["sensitivity"]}
            self.assertEqual(set(variants), {"standard_scaler_complete", "standard_scaler_average", "no_scaling_ward"})
            for item in variants.values():
                self.assertTrue(-1 <= item["ari_vs_primary"] <= 1)
                self.assertTrue(0 <= item["nmi_vs_primary"] <= 1)
                self.assertTrue(math_isfinite(item["cophenetic_correlation"]))

    def test_ari_nmi_reproducible(self):
        w = pq.ParquetFile(self.base / "hierarchical_weekday_partition.parquet").read().to_pandas().weekday_cluster_id
        h = pq.ParquetFile(self.base / "hierarchical_holiday_partition.parquet").read().to_pandas().holiday_cluster_id
        self.assertAlmostEqual(adjusted_rand_score(w, h), self.receipt["weekday_vs_holiday"]["ari"])
        self.assertAlmostEqual(normalized_mutual_info_score(w, h), self.receipt["weekday_vs_holiday"]["nmi"])

    def test_deterministic_verification_and_no_downstream_stage(self):
        self.assertTrue(all(all(checks.values()) for checks in self.receipt["reproducibility"].values()))
        self.assertFalse(self.receipt["brouter_triggered"]); self.assertFalse(self.receipt["accident_stage_triggered"])
        tree = ast.parse((self.root / "src/run_hierarchical_reconstruction.py").read_text(encoding="utf-8"))
        names = {alias.name.lower() for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names}
        self.assertFalse(any("brouter" in name or "accident" in name for name in names))


def math_isfinite(value):
    return bool(np.isfinite(float(value)))


if __name__ == "__main__": unittest.main()
