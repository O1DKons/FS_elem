"""The proposed descriptor must preserve order without encoding camera framing."""
import importlib.util
from pathlib import Path
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[1]


def example_pose(n=24):
    joints = np.array([[0., -1.5]] * 5 + [
        [-.4, -1.], [.4, -1.], [-.6, -.6], [.6, -.6],
        [-.7, -.3], [.7, -.3], [-.2, 0.], [.2, 0.],
        [-.3, .5], [.3, .5], [-.3, 1.], [.3, 1.],
    ])
    p = np.repeat(joints[None], n, axis=0)
    p[:, 13, 0] += np.linspace(0, .6, n)
    p[:, 9, 1] += np.linspace(0, .3, n)
    return p * 80 + 200, np.ones((n, 17))


class OrderedPoseTests(unittest.TestCase):
    def setUp(self):
        path = ROOT / 'work/personal-ordered-pose-v1/features.py'
        spec = importlib.util.spec_from_file_location('ordered_pose', path)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def test_per_frame_camera_translation_and_scale_do_not_change_features(self):
        p, s = example_pose()
        scale = np.linspace(.7, 1.8, len(p))[:, None, None]
        drift = np.stack([np.arange(len(p)) * 10, np.arange(len(p)) * -3], axis=-1)[:, None]
        original, detail = self.module.ordered_features(p, s, 25)
        changed, _ = self.module.ordered_features(p * scale + drift, s, 25)
        self.assertEqual(original.shape, (192,))
        np.testing.assert_allclose(original, changed, atol=1e-12)
        self.assertIsNone(detail['reason'])

    def test_reversing_motion_changes_order_without_changing_bin_contents(self):
        p, s = example_pose()
        forward, _ = self.module.ordered_features(p, s, 25)
        reverse, _ = self.module.ordered_features(p[::-1], s[::-1], 25)
        self.assertFalse(np.allclose(forward, reverse))
        np.testing.assert_allclose(forward.reshape(4, 12, 2, 2)[::-1],
                                   reverse.reshape(4, 12, 2, 2), atol=1e-12)

    def test_unseen_joint_is_not_invented_by_gap_filling(self):
        p, s = example_pose()
        s[:6, 15] = 0
        feature, detail = self.module.ordered_features(p, s, 25)
        self.assertIsNone(feature)
        self.assertEqual(detail['reason'], 'insufficient_bin_coverage')
        self.assertEqual(detail['validCounts'][0][10], 0)

    def test_confident_nan_coordinates_still_abstain(self):
        p, s = example_pose()
        p[6:12, 13] = np.nan
        feature, detail = self.module.ordered_features(p, s, 25)
        self.assertIsNone(feature)
        self.assertEqual(detail['reason'], 'insufficient_bin_coverage')

    def test_repeated_source_indices_cannot_supply_temporal_evidence(self):
        p, s = example_pose()
        feature, detail = self.module.ordered_features(p, s, 25, np.repeat(np.arange(6), 4))
        self.assertIsNone(feature)
        self.assertEqual(detail['reason'], 'insufficient_distinct_frames')


if __name__ == '__main__':
    unittest.main()
