import importlib.util
from pathlib import Path
import unittest
import numpy as np

PATH = Path(__file__).resolve().parents[1] / 'work/foot-ice-rgb-refinement-v1/geometry.py'


class FootIceRgbTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('foot_ice_geometry', PATH)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def row(self):
        p = np.full((23, 2), np.nan)
        p[[11, 13, 15, 17, 18, 19]] = [[90, 100], [90, 160], [90, 220], [100, 225], [96, 225], [85, 223]]
        s = np.where(np.isfinite(p).all(1), 1.0, 0.0)
        return dict(points=np.nan_to_num(p).tolist(), scores=s.tolist())

    def test_crop_contains_boot_and_visible_ice_without_shoulders(self):
        box = self.module.foot_ice_box(self.row(), 300, 400)
        self.assertIsNotNone(box)
        self.assertLess(box[1], 220)
        self.assertGreater(box[3], 245)
        self.assertLessEqual(box[0], 85)
        self.assertGreaterEqual(box[2], 100)

    def test_outside_frame_leg_cannot_supply_scale(self):
        row = self.row(); row['points'][11] = [-1, 100]
        self.assertIsNone(self.module.foot_ice_box(row, 300, 400))

    def test_no_complete_leg_returns_missing(self):
        row = self.row(); row['scores'][13] = 0.1
        self.assertIsNone(self.module.foot_ice_box(row, 300, 400))

    def test_crop_is_clipped_to_real_pixels(self):
        row = self.row(); row['points'] = (np.asarray(row['points'])+[0, 170]).tolist()
        box = self.module.foot_ice_box(row, 300, 400)
        self.assertEqual(box[3], 400)
        self.assertGreater(box[2]-box[0], 0)

    def test_feature_velocity_uses_actual_timestamps(self):
        t = np.array([0., .03, .08, .12]); v = (3*t)[:, None]
        x, usable = self.module.temporal_features(v, t, np.arange(4))
        np.testing.assert_allclose(x[:, 1], 3)
        self.assertTrue(usable.all())

    def test_missing_observation_and_frame_gap_are_not_bridged(self):
        t = np.array([0., .02, .04, .06, .2, .22]); v = np.array([[0.], [1.], [np.nan], [3.], [10.], [11.]])
        x, usable = self.module.temporal_features(v, t, np.array([0, 1, 2, 3, 10, 11]))
        self.assertFalse(usable[2])
        self.assertTrue(np.isnan(x[3, 1]))
        self.assertAlmostEqual(x[4, 1], 50)

    def test_duplicate_or_decreasing_timestamps_rejected(self):
        with self.assertRaises(ValueError):
            self.module.temporal_features(np.ones((3, 2)), [0., 0., .1], [0, 1, 2])


if __name__ == '__main__':
    unittest.main()
