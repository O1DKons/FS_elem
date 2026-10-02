import importlib.util
from pathlib import Path
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('stabilized_motion_features', ROOT/'work/stabilized-contact-v2/motion_features.py')
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def fixture(n=9):
    p = np.tile(np.array([[100., 100.]]), (n, 17, 1))
    p[:, 5:7] = [[90, 80], [110, 80]]
    p[:, 11:13] = [[90, 100], [110, 100]]
    p[:, 15:17] = [[85, 140], [115, 140]]
    s = np.ones((n, 17))
    m = np.tile(np.array([[1., 0, 0], [0, 1, 0]]), (n, 1, 1))
    valid = np.ones(n, bool); valid[0] = False; m[0] = np.nan
    return p, s, m, valid


class MotionTests(unittest.TestCase):
    def test_pure_camera_zoom_translation_is_removed(self):
        p, s, m, v = fixture()
        for i in range(1, len(p)):
            m[i] = [[1.02, 0, 3], [0, 1.02, -2]]
            p[i] = p[i-1] @ m[i, :, :2].T + m[i, :, 2]
        x = module.motion_features(p, s, 50, m, v)
        np.testing.assert_allclose(x[1:], 0, atol=1e-12)
        self.assertTrue(np.isnan(x[0]).all())

    def test_independent_body_translation_remains(self):
        p, s, m, v = fixture()
        for i in range(1, len(p)):
            m[i, :, 2] = [3, 2]
            p[i] = p[i-1] + [5, 1]
        x = module.motion_features(p, s, 50, m, v)
        np.testing.assert_allclose(x[1:], np.tile([5., -2.5] * 3, (8, 1)))

    def test_invalid_camera_center_is_not_filled(self):
        p, s, m, v = fixture(); v[4] = False; m[4] = np.nan
        x = module.motion_features(p, s, 50, m, v)
        self.assertTrue(np.isnan(x[4]).all())
        self.assertTrue(np.isfinite(x[[3, 5]]).all())

    def test_confidence_gaps_and_nonfinite_scores_are_missing(self):
        p, s, m, v = fixture(); s[4, 15] = np.nan
        x = module.motion_features(p, s, 50, m, v)
        self.assertTrue(np.isfinite(x[4:6, :4]).all())
        self.assertTrue(np.isnan(x[4:6, 4:]).all())

    def test_pair_swaps_are_invariant(self):
        p, s, m, v = fixture()
        p += np.arange(len(p))[:, None, None]
        expected = module.motion_features(p, s, 50, m, v)
        for left, right in [(5, 6), (11, 12), (15, 16)]:
            p[::2, [left, right], :] = p[::2, [right, left], :]
        np.testing.assert_allclose(module.motion_features(p, s, 50, m, v), expected, equal_nan=True)

    def test_insufficient_neighbors_stay_missing(self):
        p, s, m, v = fixture(); v[:] = False; v[4] = True; m[~v] = np.nan
        self.assertTrue(np.isnan(module.motion_features(p, s, 50, m, v)).all())

    def test_bad_torso_does_not_create_motion(self):
        p, s, m, v = fixture(); p[4, 5:7] = p[4, 11:13]
        self.assertTrue(np.isnan(module.motion_features(p, s, 50, m, v)[4]).all())

    def test_invalid_inputs_rejected(self):
        p, s, m, v = fixture()
        with self.assertRaises(ValueError): module.motion_features(p, s, 0, m, v)
        with self.assertRaises(ValueError): module.motion_features(p, s, 50, m[:-1], v)


if __name__ == '__main__': unittest.main()
