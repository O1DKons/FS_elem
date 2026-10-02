import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_motionbert_yaw_only import evaluate_records


def record(attempt_id, athlete, label, values):
    return {
        "attemptId": attempt_id,
        "athlete": athlete,
        "visualTruth": label,
        "featureValues": values,
    }


class MotionBertYawOnlyTests(unittest.TestCase):
    def test_evaluation_keeps_athletes_in_disjoint_folds(self):
        records = [
            record("a1", "A", "apparently_complete", [0, 0, 0, 0]),
            record("a2", "A", "apparently_short", [1, 1, 1, 1]),
            record("b1", "B", "apparently_complete", [0.1, 0, 0, 0]),
            record("b2", "B", "apparently_short", [1.1, 1, 1, 1]),
            record("c1", "C", "apparently_complete", [-0.1, 0, 0, 0]),
            record("c2", "C", "apparently_short", [0.9, 1, 1, 1]),
        ]

        result = evaluate_records(records)

        self.assertEqual(result["yawOnly"]["metrics"]["n"], 6)
        self.assertEqual(result["classCounts"], {"apparently_complete": 3, "apparently_short": 3})
        self.assertEqual(len(result["folds"]), 3)
        for fold in result["folds"]:
            self.assertNotIn(fold["heldOutAthlete"], fold["trainingAthletes"])

    def test_rejects_missing_or_non_finite_features(self):
        bad = [record("a", "A", "apparently_short", [1, 2, 3, np.nan])]
        with self.assertRaisesRegex(ValueError, "four finite yaw features"):
            evaluate_records(bad)

    def test_rejects_duplicate_attempt_or_unclear_target(self):
        duplicate = [
            record("a", "A", "apparently_short", [1, 2, 3, 4]),
            record("a", "B", "apparently_complete", [4, 3, 2, 1]),
        ]
        with self.assertRaisesRegex(ValueError, "unique non-empty strings"):
            evaluate_records(duplicate)

        unclear = [record("b", "B", "unclear", [1, 2, 3, 4])]
        with self.assertRaisesRegex(ValueError, "visual target"):
            evaluate_records(unclear)


if __name__ == "__main__":
    unittest.main()
