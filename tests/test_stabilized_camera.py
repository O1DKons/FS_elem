"""Synthetic contracts for label-free masked-background camera estimation."""
import hashlib
import os
import inspect
import json
import tempfile
from pathlib import Path
import sys
import unittest
import cv2
import numpy as np

HERE = Path(__file__).resolve().parents[1] / 'work' / os.environ.get('STABILIZED_CAMERA_VERSION', 'stabilized-contact-v2')
sys.path.insert(0, str(HERE))


class CameraTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((HERE / 'camera.py').is_file(), 'Camera estimator must exist')
        import camera
        self.camera = camera
        rng = np.random.default_rng(21)
        self.background = cv2.GaussianBlur(rng.integers(0, 256, (360, 640), dtype=np.uint8), (3, 3), 0)
        self.points = np.tile([320., 180.], (17, 1))
        self.points[[5, 6, 11, 12]] = [[300, 145], [340, 145], [300, 210], [340, 210]]
        self.points[[0, 15, 16]] = [[320, 115], [295, 245], [345, 245]]
        self.scores = np.ones(17)

    def estimate(self, previous, current, previous_points=None, current_points=None, scores=None, full_shape=(360, 640)):
        return self.camera.estimate_pair(previous, current,
            self.points if previous_points is None else previous_points,
            self.points if current_points is None else current_points,
            self.scores, self.scores if scores is None else scores,
            full_shape=full_shape)

    def test_recovers_background_similarity_despite_independent_body_motion(self):
        expected = cv2.getRotationMatrix2D((320, 180), 0.5, 1.002)
        expected[:, 2] += [3, -2]
        current = cv2.warpAffine(self.background, expected, (640, 360), borderMode=cv2.BORDER_REFLECT)
        previous = self.background.copy()
        previous[120:240, 295:345] = 0
        current[120:240, 305:355] = 255
        moved = self.points + [10, 0]
        result = self.estimate(previous, current, current_points=moved)
        self.assertTrue(result['valid'], result)
        np.testing.assert_allclose(result['matrix_prev_to_current'], expected, atol=.15)
        self.assertGreaterEqual(result['inliers_count'], 15)
        self.assertGreaterEqual(result['inlier_fraction'], .6)

    def test_masked_body_motion_cannot_be_accepted_as_camera_motion(self):
        previous = np.zeros((360, 640), np.uint8)
        previous[125:235, 295:345] = self.background[125:235, 295:345]
        current = np.zeros_like(previous)
        current[125:235, 303:353] = previous[125:235, 295:345]
        result = self.estimate(previous, current, current_points=self.points + [8, 0])
        self.assertFalse(result['valid'])
        self.assertTrue(np.isnan(result['matrix_prev_to_current']).all())

    def test_textureless_pair_preserves_invalid_not_identity(self):
        blank = np.zeros((360, 640), np.uint8)
        result = self.estimate(blank, blank)
        self.assertFalse(result['valid'])
        self.assertTrue(np.isnan(result['matrix_prev_to_current']).all())

    def test_missing_hip_prevents_trusting_mask(self):
        scores = self.scores.copy()
        scores[11] = .29
        result = self.estimate(self.background, self.background, scores=scores)
        self.assertFalse(result['valid'])
        self.assertFalse(result['current_pose_mask_valid'])
        self.assertTrue(np.isnan(result['matrix_prev_to_current']).all())

    def test_low_confidence_leg_texture_is_never_camera_motion(self):
        # All visible texture belongs to a moving lower body below the trusted torso.
        previous = np.zeros((360, 640), np.uint8)
        previous[245:345, 220:400] = self.background[245:345, 220:400]
        current = np.zeros_like(previous)
        current[245:345, 228:408] = previous[245:345, 220:400]
        points = np.tile([320., 130.], (17, 1))
        points[[0, 5, 6, 11, 12]] = [[320, 75], [300, 100], [340, 100], [300, 170], [340, 170]]
        points[[13, 14, 15, 16]] = [[270, 260], [350, 260], [260, 330], [360, 330]]
        scores = self.scores.copy()
        scores[[13, 14, 15, 16]] = .1
        result = self.camera.estimate_pair(previous, current, points, points + [8, 0],
            scores, scores, full_shape=(360, 640))
        self.assertFalse(result['valid'], result)
        self.assertEqual(result['reason'], 'untrusted_pose_mask')
        self.assertTrue(np.isnan(result['matrix_prev_to_current']).all())

    def test_missing_any_required_joint_rejects_both_pair_endpoints(self):
        # Omitting either wrist, either leg joint, nose, elbow, shoulder or hip is unsafe.
        for joint in [0, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]:
            for invalid_endpoint in ['previous', 'current']:
                with self.subTest(joint=joint, endpoint=invalid_endpoint):
                    damaged = self.scores.copy()
                    damaged[joint] = .29
                    before = damaged if invalid_endpoint == 'previous' else self.scores
                    after = damaged if invalid_endpoint == 'current' else self.scores
                    result = self.camera.estimate_pair(self.background, self.background,
                        self.points, self.points, before, after, full_shape=(360, 640))
                    self.assertFalse(result['valid'])
                    self.assertFalse(result[invalid_endpoint + '_pose_mask_valid'])
                    self.assertTrue(np.isnan(result['matrix_prev_to_current']).all())

    def test_nonfinite_required_extremity_rejects_mask(self):
        for joint in [0, 7, 8, 9, 10, 13, 14, 15, 16]:
            with self.subTest(joint=joint):
                damaged = self.points.copy()
                damaged[joint, 0] = np.nan
                result = self.estimate(self.background, self.background, current_points=damaged)
                self.assertFalse(result['valid'])
                self.assertFalse(result['current_pose_mask_valid'])
                self.assertTrue(np.isnan(result['matrix_prev_to_current']).all())

    def test_pair_returns_full_resolution_translation(self):
        expected = np.array([[1., 0., 4.], [0., 1., -3.]])
        current = cv2.warpAffine(self.background, expected, (640, 360), borderMode=cv2.BORDER_REFLECT)
        result = self.estimate(self.background, current, previous_points=self.points * 2,
            current_points=(self.points + [4, -3]) * 2, full_shape=(720, 1280))
        self.assertTrue(result['valid'], result)
        np.testing.assert_allclose(result['matrix_prev_to_current'], [[1, 0, 8], [0, 1, -6]], atol=.2)

    def test_rescale_handles_rounded_nonuniform_scale_without_losing_rotation(self):
        scaled = np.array([[.99, -.02, 4.], [.02, .99, -3.]])
        full = self.camera.rescale_matrix(scaled, (720, 1280), (359, 640))
        # Independently map one full-resolution point into the resized image and back.
        np.testing.assert_allclose(full @ [128., 72., 1.], [133.284, 67.83041782729805], atol=1e-8)


class ExtractionTests(unittest.TestCase):
    def test_extracts_all_native_frames_and_rejects_stale_resume(self):
        self.assertTrue((HERE / 'extract.py').is_file(), 'Resumable extractor must exist')
        import extract as extractor
        sys.path.insert(0, str(HERE.parents[1] / 'scripts'))
        from extract_dense_pose_type import extract as native_extract
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            video = directory / 'synthetic.avi'
            writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'MJPG'), 25., (640, 360))
            self.assertTrue(writer.isOpened())
            rng = np.random.default_rng(7)
            gray = cv2.GaussianBlur(rng.integers(0, 256, (360, 640), dtype=np.uint8), (3, 3), 0)
            for _ in range(4):
                writer.write(cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR))
            writer.release()
            sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
            points = np.tile([320., 180.], (4, 17, 1))
            points[:, [5, 6, 11, 12]] = [[300, 145], [340, 145], [300, 210], [340, 210]]
            provenance = dict(native_extraction_sha256=hashlib.sha256(inspect.getsource(native_extract).encode()).hexdigest(),
                sampling='every decoded source frame; nominal FPS timestamps; no uniform32 reduction')
            native = directory / 'native.npz'
            np.savez_compressed(native, points=points, scores=np.ones((4, 17)), fps=25.,
                frame_indices=np.arange(4), times=np.arange(4)/25., source_sha256=sha(video),
                provenance=json.dumps(provenance))
            record = dict(attemptId='synthetic', clipSha256=sha(video), nativeCacheSha256=sha(native),
                nativeProvenance=provenance, frames=4, fps=25.)
            cache = directory / 'cache'
            contract = extractor.camera_contract()
            path = extractor.extract_one(video, native, record, cache, contract)
            with np.load(path, allow_pickle=False) as data:
                self.assertEqual(data['valid'].tolist(), [False, True, True, True])
                self.assertTrue(np.isnan(data['matrix_prev_to_current'][0]).all())
                self.assertEqual(data['frame_shape'].tolist(), [360, 640])
                self.assertEqual(data['frame_indices'].tolist(), [0, 1, 2, 3])
                np.testing.assert_allclose(data['matrix_prev_to_current'][1:],
                    np.tile([[1, 0, 0], [0, 1, 0]], (3, 1, 1)), atol=.02)
            before = sha(path)
            self.assertEqual(extractor.extract_one(video, native, record, cache, contract), path)
            self.assertEqual(sha(path), before)
            with self.assertRaisesRegex(ValueError, 'provenance'):
                extractor.extract_one(video, native, record, cache, dict(contract, version='changed'))
            record['nativeCacheSha256'] = '0' * 64
            with self.assertRaisesRegex(ValueError, 'Native cache SHA'):
                extractor.extract_one(video, native, record, cache, contract)


if __name__ == '__main__':
    unittest.main()
