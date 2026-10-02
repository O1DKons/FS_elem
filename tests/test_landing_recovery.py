"""Geometry and missing-evidence guards for the landing recovery probe."""
import importlib.util
from pathlib import Path
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def load():
    path = ROOT / 'work/landing-recovery-v1/features.py'
    spec = importlib.util.spec_from_file_location('landing_recovery', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def example():
    p = np.zeros((40, 17, 2), float)
    joints = {0: (20, 5), 5: (10, 20), 6: (30, 20), 11: (12, 45),
              12: (28, 45), 13: (10, 65), 14: (35, 62), 15: (12, 90), 16: (38, 87)}
    for k, xy in joints.items():
        p[:, k] = xy
    return p, np.ones((40, 17)), 50., np.arange(40), .3, np.ones(40, bool)


def runner():
    spec = importlib.util.spec_from_file_location('landing_recovery_run', ROOT / 'work/landing-recovery-v1/run.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LandingRecoveryTests(unittest.TestCase):
    def test_eight_finite_features_and_fixed_window_counts(self):
        vector, detail = load().landing_features(*example())
        self.assertEqual(vector.shape, (8,))
        self.assertTrue(np.isfinite(vector).all())
        self.assertEqual([w['expectedFrames'] for w in detail['windows']], [6, 10])

    def test_left_right_swaps_at_arbitrary_frames_do_not_change_features(self):
        args = list(example()); before, _ = load().landing_features(*args)
        p = args[0].copy()
        for a, b in ((5, 6), (11, 12), (13, 14), (15, 16)):
            p[::2, [a, b]] = p[::2, [b, a]]
        args[0] = p
        after, _ = load().landing_features(*args)
        np.testing.assert_allclose(before, after)

    def test_camera_translation_and_uniform_scale_do_not_change_features(self):
        args = list(example()); before, _ = load().landing_features(*args)
        args[0] = args[0] * 3 + [100, 500]
        after, _ = load().landing_features(*args)
        np.testing.assert_allclose(before, after)

    def test_unverified_source_frames_do_not_count_as_evidence(self):
        args = list(example()); args[5][15:25] = False
        vector, detail = load().landing_features(*args)
        self.assertIsNone(vector)
        self.assertEqual(detail['windows'][1]['validFrames'], 0)

    def test_confidence_gaps_are_not_filled_or_hidden(self):
        args = list(example()); args[1][15:21, 0] = 0
        vector, detail = load().landing_features(*args)
        self.assertIsNone(vector)
        self.assertEqual(detail['windows'][1]['expectedFrames'], 10)
        self.assertEqual(detail['windows'][1]['validFrames'], 4)

    def test_missing_tail_and_repeated_indices_cannot_create_coverage(self):
        args = list(example())
        for k in (0, 1, 3, 5):
            args[k] = args[k][:18]
        self.assertIsNone(load().landing_features(*args)[0])
        args = list(example()); args[3][20] = args[3][19]
        with self.assertRaises(ValueError):
            load().landing_features(*args)

    def test_heldout_label_cannot_change_prediction_or_training_majority(self):
        m = runner()
        rows = [dict(id=str(i), athleteKey=str(i), sourceSha256=str(i), clipSha256=str(i),
                     truth='complete' if i % 2 else 'short') for i in range(5)]
        features = {k: [np.arange(8) * (i + 1.) for i in range(5)] for k in m.VARIANTS}
        before = m.evaluate_fold(rows, features, [0, 1, 2, 3], [4])[1]
        rows[4]['truth'] = 'complete'
        after = m.evaluate_fold(rows, features, [0, 1, 2, 3], [4])[1]
        self.assertEqual(before, after)
        rows[4]['sourceSha256'] = rows[0]['sourceSha256']
        with self.assertRaises(ValueError):
            m.evaluate_fold(rows, features, [0, 1, 2, 3], [4])

    def test_abstentions_stay_in_both_class_denominators(self):
        m = runner()
        result = m.summarize(['complete', 'complete', 'short'], ['complete', 'abstain', 'abstain'])
        self.assertEqual(result['accuracy'], 1 / 3)
        self.assertEqual(result['recall'], {'complete': .5, 'short': 0.})
        self.assertEqual(result['balancedAccuracy'], .25)
        self.assertEqual(result['abstentions'], 2)


if __name__ == '__main__':
    unittest.main()
