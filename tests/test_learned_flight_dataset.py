import importlib.util
from pathlib import Path
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('learned_flight_dataset', ROOT/'work/full-program-learned-flight-v1/dataset.py')
module = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(module)


def event(kind='axel', lo=6, hi=24):
    return dict(eventClass=kind, lastContactFrame=lo, firstContactFrame=hi)


class DatasetTests(unittest.TestCase):
    def test_partial_review_never_creates_background(self):
        np.testing.assert_array_equal(module.sample_targets(np.arange(0, 31, 6), [event()], False), [-1, -1, 1, 1, -1, -1])

    def test_full_review_includes_non_axel_flight_and_contacts_are_background(self):
        np.testing.assert_array_equal(module.sample_targets(np.arange(0, 31, 6), [event('other_jump')], True), [0, 0, 1, 1, 0, 0])

    def test_uncertain_interval_is_unknown_even_with_full_review(self):
        np.testing.assert_array_equal(module.sample_targets(np.arange(0, 31, 6), [event('uncertain')], True), [0, -1, -1, -1, -1, 0])

    def test_overlapping_confirmed_intervals_are_rejected(self):
        with self.assertRaises(ValueError): module.sample_targets(np.arange(0, 31, 6), [event(), event()], True)

    def test_derivative_uses_sample_times_and_missing_pose_is_unusable(self):
        times = [0., .119, .24, .36]
        frames = []
        for i, t in enumerate(times):
            points = {'left_shoulder': (19., 10.), 'right_shoulder': (21., 10.),
                      'left_hip': (19., 20.), 'right_hip': (21., 20.), 'left_wrist': (20.+2*t, 15.)}
            frames.append(dict(frameIndex=i*6, time=t, landmarks=[dict(name=k, x=x/100, y=y/100, confidence=1) for k, (x, y) in points.items()]))
        pose = dict(frames=frames, source=dict(fps=50, frameCount=19, width=100, height=100),
                    sampling=dict(stepSourceFrames=6, actualRate=50/6))
        x, usable, indices, measured = module.pose_arrays(pose)
        self.assertTrue(usable.all()); self.assertEqual(x.shape, (4, 68))
        np.testing.assert_allclose(x[:, 34+9*2], .2, atol=1e-12)
        pose['frames'][2]['landmarks'] = []
        self.assertFalse(module.pose_arrays(pose)[1][2])


if __name__ == '__main__': unittest.main()
