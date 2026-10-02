import math
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "work/motionbert-rotation-probe-v1"))
from motionbert_rotation_probe import coco17_to_h36m_frame, strip_dataparallel_prefix, torso_yaw_features


def pose_frame():
    names = ["nose", "left_eye", "right_eye", "left_ear", "right_ear",
             "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
             "left_wrist", "right_wrist", "left_hip", "right_hip",
             "left_knee", "right_knee", "left_ankle", "right_ankle"]
    landmarks = [{"name": name, "x": i / 20, "y": i / 40, "confidence": 1.0}
                 for i, name in enumerate(names)]
    return {"landmarks": landmarks}


class MotionBertProbeTests(unittest.TestCase):
    def test_strips_only_uniform_dataparallel_prefix(self):
        state = {"module.layer.weight": 1, "module.layer.bias": 2}
        self.assertEqual(strip_dataparallel_prefix(state), {"layer.weight": 1, "layer.bias": 2})
        mixed = {"layer.weight": 1, "module.layer.bias": 2}
        self.assertEqual(strip_dataparallel_prefix(mixed), mixed)

    def test_converts_mediapipe_body_landmarks_to_h36m17_order(self):
        result = coco17_to_h36m_frame(pose_frame(), 100, 200)
        self.assertEqual(result.shape, (17, 3))
        # H36M index 1 is right hip; index 4 is left hip.
        self.assertTrue(np.allclose(result[1], [60, 60, 1]))
        self.assertTrue(np.allclose(result[4], [55, 55, 1]))
        self.assertTrue(np.allclose(result[0, :2], [57.5, 57.5]))
        self.assertTrue(np.allclose(result[8, :2], [27.5, 27.5]))

    def test_torso_yaw_wraps_angles_and_does_not_bridge_invalid_frames(self):
        xyz = np.zeros((4, 17, 3), dtype=float)
        for index, degrees in enumerate([170, -170, 45, 80]):
            angle = math.radians(degrees)
            axis = np.array([math.cos(angle), 0.0, math.sin(angle)])
            xyz[index, 11] = axis
            xyz[index, 14] = [0, 0, 0]
            xyz[index, 4] = axis
            xyz[index, 1] = [0, 0, 0]
        valid = np.array([True, True, False, True])
        features, quality = torso_yaw_features(xyz, valid, valid)
        self.assertAlmostEqual(features[0], 20.0)
        self.assertAlmostEqual(features[1], 20.0)
        self.assertAlmostEqual(features[2], 20.0)
        self.assertAlmostEqual(features[3], 20.0)
        self.assertEqual(quality["shoulderAdjacentPairs"], 1)
        self.assertEqual(quality["hipAdjacentPairs"], 1)


if __name__ == "__main__":
    unittest.main()
