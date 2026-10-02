import importlib.util
from pathlib import Path
import sys
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
path = ROOT / 'work/personal-rtmw-cascade-transfer-v1/windows.py'
spec = importlib.util.spec_from_file_location('personal_pts_windows', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RealSourceWindowTests(unittest.TestCase):
    def test_selection_uses_real_pts_not_container_fps_or_expert_contacts(self):
        times = np.array([0., .018, .034, .051, .069, .085])
        window = module.dense_window(times, .02, .07)
        self.assertEqual(window['flightFrames'], [2, 3, 4])
        self.assertEqual(window['startSeconds'], .02)
        self.assertEqual(window['endSeconds'], .07)

    def test_frames_exactly_at_boundaries_are_excluded_from_flight(self):
        window = module.dense_window(np.linspace(0, 1, 11), .2, .7)
        self.assertEqual(window['flightFrames'], [3, 4, 5, 6])

    def test_invalid_timeline_or_bounds_are_rejected(self):
        for times, start, end in [([0., .1, .1], 0., .1), ([0., .1, .2], .2, .1),
            ([0., .1, float('nan')], 0., .1), ([0., .1, .2], -.1, .1), ([0., .1, .2], 0., 2.)]:
            with self.subTest(times=times), self.assertRaises(ValueError):
                module.dense_window(times, start, end)

    def test_cfr_nominal_features_match_original81d_recipe(self):
        times = np.arange(40) / 50
        window = module.dense_window(times, .1, .5)
        frames = {}
        signals = []
        for i in range(40):
            points = np.zeros((23, 2));points[5:7] = [[10, 20], [20, 20]]
            points[11:13] = [[10+np.sin(i), 50], [20+np.cos(i), 50]]
            frames[str(i)] = dict(points=points.tolist(), scores=[.9]*23)
            if i in window['flightFrames']:
                scale = np.linalg.norm((points[5]+points[6]-points[11]-points[12])/2)
                signals.append(np.r_[(points[12]-points[11])/scale, (points[6]-points[5])/scale])
        values = np.array(signals)
        expected = np.r_[.4, *[module.spectrum(values[:, j]) for j in range(4)]]
        x, quality = module.nominal_features(dict(frames=frames), window)
        np.testing.assert_allclose(x, expected, rtol=0, atol=0)
        self.assertEqual(quality['finiteSpectralFeatures'], 80)

    def test_missing_points_remain_missing_and_do_not_claim_observed_rotation(self):
        window = module.dense_window(np.arange(12) / 50, .02, .2)
        document = dict(frames={str(i): dict(points=[], scores=[]) for i in range(12)})
        x, quality = module.nominal_features(document, window)
        self.assertTrue(np.isnan(x[1:]).all())
        self.assertEqual(quality['usableTorsoFrames'], 0)
        self.assertAlmostEqual(x[0], .18)


if __name__ == '__main__':
    unittest.main()
