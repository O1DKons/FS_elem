import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_scan_threshold import binary_margin, nested_group_threshold_cv, select_balanced_threshold


class ScanThresholdAuditTests(unittest.TestCase):
    def test_margin_compares_best_axel_score_with_other_score(self):
        scores = np.array([[0.1, 0.8, -0.2, 0.3], [0.2, -0.1, 0.4, 0.6]])
        margins = binary_margin(scores, ["1A", "2A", "3A", "other"])
        np.testing.assert_allclose(margins, [0.5, -0.2])

    def test_balanced_threshold_separates_classes_and_breaks_ties_conservatively(self):
        result = select_balanced_threshold(
            np.array([-0.9, 0.1, 0.8, 0.9]),
            np.array([0, 0, 1, 1]),
        )
        self.assertEqual(result["threshold"], 0.1)
        self.assertEqual(result["balancedAccuracy"], 1.0)
        self.assertEqual(result["recall"], 1.0)
        self.assertEqual(result["specificity"], 1.0)

    def test_rejects_missing_other_class_and_single_class_threshold_data(self):
        with self.assertRaisesRegex(ValueError, "other"):
            binary_margin(np.array([[1.0, 2.0]]), ["1A", "2A"])
        with self.assertRaisesRegex(ValueError, "both classes"):
            select_balanced_threshold(np.array([0.1, 0.2]), np.array([1, 1]))

    def test_nested_threshold_validation_keeps_each_group_out_of_its_training_fold(self):
        features, labels, groups = [], [], []
        for group in ("A", "B", "C", "D", "E", "F"):
            features.extend(([-2.0, 0.0], [2.0, 0.0]))
            labels.extend(("other", "1A"))
            groups.extend((group, group))

        result = nested_group_threshold_cv(
            np.asarray(features), np.asarray(labels), np.asarray(groups),
            outer_splits=3, inner_splits=2,
        )

        self.assertEqual(result["metrics"]["balancedAccuracy"], 1.0)
        for fold in result["folds"]:
            self.assertFalse(set(fold["trainingGroups"]) & set(fold["heldOutGroups"]))


if __name__ == "__main__":
    unittest.main()
