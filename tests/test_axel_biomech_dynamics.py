import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "work/axel-biomech-dynamics-v1"))
from axel_biomech_dynamics import extract_dynamic_features, same_fold_partitions


def frame(index, shift=0.0, confidence=1.0):
    points = {
        "left_shoulder": (40, 40), "right_shoulder": (60, 40),
        "left_hip": (40, 60), "right_hip": (60, 60),
        "left_wrist": (40 - shift, 40), "right_wrist": (60 + shift, 40),
        "left_ankle": (40, 80 + shift), "right_ankle": (60, 80 + shift),
    }
    return {
        "frameIndex": index,
        "landmarks": [
            {"name": name, "x": x / 100, "y": y / 100, "confidence": confidence}
            for name, (x, y) in points.items()
        ],
    }


class DynamicFeatureTests(unittest.TestCase):
    def test_fold_comparison_ignores_train_only_preprocessor_state(self):
        folds_a = [{"trainIndices": [1, 2], "testIndices": [0], "mean": [0.1]}]
        folds_b = [{"trainIndices": [1, 2], "testIndices": [0], "mean": [0.9]}]
        self.assertTrue(same_fold_partitions(folds_a, folds_b))

    def test_uses_only_strict_flight_frames_and_normalizes_compactness(self):
        pose = {
            "coordinateSpace": {"width": 100, "height": 100},
            "frames": [frame(1, 99), frame(2, 0), frame(3, 10), frame(4, 99)],
        }
        bounds = {
            "lastContact": {"frameIndex": 1},
            "firstContact": {"frameIndex": 4},
        }
        values, quality = extract_dynamic_features(pose, bounds)
        self.assertEqual(quality["flightFrames"], 2)
        self.assertEqual(quality["validFrames"], 2)
        self.assertAlmostEqual(values[0], 1.0)
        self.assertAlmostEqual(values[1], 0.857172, places=5)
        self.assertAlmostEqual(values[2], 1.049793, places=5)
        self.assertAlmostEqual(values[3], 0.0)
        self.assertAlmostEqual(values[4], -0.48155, places=4)
        self.assertAlmostEqual(values[5], 1.049793, places=5)

    def test_low_confidence_frames_are_missing_not_interpolated(self):
        pose = {
            "coordinateSpace": {"width": 100, "height": 100},
            "frames": [frame(2, confidence=0.1)],
        }
        bounds = {
            "lastContact": {"frameIndex": 1},
            "firstContact": {"frameIndex": 3},
        }
        values, quality = extract_dynamic_features(pose, bounds)
        self.assertEqual(quality["validFrames"], 0)
        self.assertEqual(quality["coverage"], 0.0)
        self.assertTrue(all(math.isnan(value) for value in values[1:]))


if __name__ == "__main__":
    unittest.main()
