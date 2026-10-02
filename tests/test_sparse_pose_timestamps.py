import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'work/full-program-learned-flight-v1')]
from dataset import pose_arrays as legacy_arrays
path = ROOT / 'scripts/sparse_pose_timestamps.py'
if path.exists():
    spec = importlib.util.spec_from_file_location('sparse_pts', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
else:
    module = None

NAMES = ('nose', 'left_eye', 'right_eye', 'left_ear', 'right_ear', 'left_shoulder',
         'right_shoulder', 'left_elbow', 'right_elbow', 'left_wrist', 'right_wrist',
         'left_hip', 'right_hip', 'left_knee', 'right_knee', 'left_ankle', 'right_ankle')


def fixture(fps=50., times=None):
    times = [i / 50 for i in range(19)] if times is None else times
    expected = dict(sourceSha256='a' * 64, fps=fps, frameCount=19, width=640, height=480,
        poseSha256='b' * 64, detectorSha256='c' * 64, stepSourceFrames=6, requestedFps=8.333333)
    expected['timestampsSha256'] = hashlib.sha256(json.dumps(times, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    timeline = dict(sourceSha256=expected['sourceSha256'], fps=fps, frameCount=19,
                    width=640, height=480, timestampsSeconds=times)
    frames = []
    for i in range(0, 19, 6):
        points = [dict(name=n, x=.35 + j * .003 + times[i] * .005 * (j + 1),
                       y=.2 + j * .02, confidence=.9) for j, n in enumerate(NAMES)]
        frames.append(dict(frameIndex=i, time=times[i], landmarks=points))
    pose = dict(source=dict(sha256=expected['sourceSha256'], fps=fps, frameCount=19, width=640, height=480),
        model=dict(poseSha256=expected['poseSha256'], detectorSha256=expected['detectorSha256']),
        sampling=dict(stepSourceFrames=6, requestedFps=8.333333, actualRate=fps / 6), frames=frames)
    return pose, timeline, expected


class SparseTimestampTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(module, 'Real-timestamp sparse adapter is missing')

    def test_cfr_geometry_gradients_and_missing_masks_match_legacy_exactly(self):
        pose, timeline, expected = fixture()
        pose['frames'][1]['landmarks'][7]['confidence'] = .1
        before = copy.deepcopy(pose)
        for old, new in zip(legacy_arrays(pose), module.pose_arrays_pts(pose, timeline, expected)):
            np.testing.assert_allclose(old, new, rtol=0, atol=0, equal_nan=True)
        self.assertEqual(pose, before)

    def test_container_fps_mismatch_uses_bound_real_times_without_relaxing_legacy(self):
        pose, timeline, expected = fixture(fps=52.)
        with self.assertRaises(ValueError):
            legacy_arrays(pose)
        x, usable, indices, times = module.pose_arrays_pts(pose, timeline, expected)
        np.testing.assert_array_equal(indices, [0, 6, 12, 18])
        np.testing.assert_array_equal(times, [0., .12, .24, .36])
        np.testing.assert_allclose(x[:, 34:], np.gradient(x[:, :34], times, axis=0), equal_nan=True)
        self.assertTrue(usable.all())
        self.assertEqual(pose['source']['fps'], 52.)

    def test_nonuniform_time_derivatives_follow_actual_observations(self):
        timeline = np.linspace(0, .36, 19).tolist()
        timeline[7:] = [t + .007 for t in timeline[7:]]
        pose, source, expected = fixture(times=timeline)
        x, _, _, times = module.pose_arrays_pts(pose, source, expected)
        np.testing.assert_allclose(x[:, 34:], np.gradient(x[:, :34], times, axis=0), equal_nan=True)
        self.assertEqual(times[-1], .367)
        self.assertFalse(np.allclose(x[:, 34:], np.gradient(x[:, :34], axis=0) * expected['fps'] / 6))

    def test_wrong_source_model_or_sampling_is_rejected_against_external_contract(self):
        for path, value in [(('source', 'sha256'), 'd' * 64), (('model', 'poseSha256'), 'd' * 64),
            (('model', 'detectorSha256'), 'd' * 64), (('sampling', 'stepSourceFrames'), 5),
            (('sampling', 'requestedFps'), 10.)]:
            pose, timeline, expected = fixture()
            pose[path[0]][path[1]] = value
            with self.subTest(path=path), self.assertRaises(ValueError):
                module.pose_arrays_pts(pose, timeline, expected)

    def test_pose_timestamp_cannot_replace_verified_source_pts(self):
        pose, timeline, expected = fixture()
        pose['frames'][1]['time'] += .001
        with self.assertRaises(ValueError):
            module.pose_arrays_pts(pose, timeline, expected)

    def test_valid_but_replaced_timeline_fails_external_digest(self):
        pose, timeline, expected = fixture()
        timeline['timestampsSeconds'] = [t * 1.01 for t in timeline['timestampsSeconds']]
        for frame in pose['frames']:
            frame['time'] = timeline['timestampsSeconds'][frame['frameIndex']]
        with self.assertRaises(ValueError):
            module.pose_arrays_pts(pose, timeline, expected)

    def test_incomplete_reordered_or_invalid_timeline_is_rejected(self):
        for change in ('short', 'duplicate', 'reverse', 'nan', 'wrong_source'):
            pose, timeline, expected = fixture()
            if change == 'short': timeline['timestampsSeconds'].pop()
            if change == 'duplicate': timeline['timestampsSeconds'][3] = timeline['timestampsSeconds'][2]
            if change == 'reverse': timeline['timestampsSeconds'].reverse()
            if change == 'nan': timeline['timestampsSeconds'][4] = float('nan')
            if change == 'wrong_source': timeline['sourceSha256'] = 'd' * 64
            with self.subTest(change=change), self.assertRaises(ValueError):
                module.pose_arrays_pts(pose, timeline, expected)

    def test_missing_pose_remains_nan_and_unusable_without_zero_filling(self):
        pose, timeline, expected = fixture()
        pose['frames'][1]['landmarks'] = []
        x, usable, _, _ = module.pose_arrays_pts(pose, timeline, expected)
        self.assertTrue(np.isnan(x[1, :34]).all())
        self.assertFalse(usable[1])

    def test_truncated_sampling_and_duplicate_landmarks_are_rejected(self):
        for change in ('truncate', 'duplicate'):
            pose, timeline, expected = fixture()
            if change == 'truncate': pose['frames'].pop()
            else: pose['frames'][0]['landmarks'].append(pose['frames'][0]['landmarks'][0].copy())
            with self.subTest(change=change), self.assertRaises(ValueError):
                module.pose_arrays_pts(pose, timeline, expected)


if __name__ == '__main__':
    unittest.main()
