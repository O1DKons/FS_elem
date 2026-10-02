import importlib.util
from pathlib import Path
import unittest
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('person_rgb_features', ROOT/'work/person-rgb-flight-v1/features.py')
feature = importlib.util.module_from_spec(spec)
spec.loader.exec_module(feature)


class PersonRgbFlightTests(unittest.TestCase):
    def test_crop_clips_padding_to_source_without_requiring_landmarks(self):
        self.assertEqual(feature.person_box([-5, 0, 50, 100], 200, 120), [0, 0, 56, 110])
        self.assertIsNone(feature.person_box(None, 200, 120))
        self.assertIsNone(feature.person_box([300, 0, 350, 100], 200, 120))

    def test_bad_bbox_is_rejected(self):
        for box in ([10, 0, 5, 100], [0, 0, float('nan'), 40], [1, 2, 3]):
            with self.assertRaises(ValueError): feature.person_box(box, 200, 120)

    def test_letterbox_preserves_head_and_feet(self):
        a = np.zeros((400, 100, 3), dtype=np.uint8)
        a[:60] = [255, 0, 0]; a[-60:] = [0, 255, 0]
        b = np.asarray(feature.letterbox(Image.fromarray(a)))
        self.assertEqual(b.shape, (224, 224, 3))
        self.assertTrue((b[5,112] == [255, 0, 0]).all())
        self.assertTrue((b[219,112] == [0, 255, 0]).all())
        self.assertTrue((b[:,0] == 0).all())

    def test_whole_target_selection_does_not_depend_on_labels(self):
        times = np.arange(12)*.12
        np.testing.assert_array_equal(feature.required_samples(times, np.full(12,-1), True), np.arange(12))

    def test_partial_source_keeps_context_but_does_not_invent_labels(self):
        times = np.arange(12)*.12; y = np.full(12,-1); y[5] = 1
        np.testing.assert_array_equal(feature.required_samples(times, y, False), [3,4,5,6,7])
        np.testing.assert_array_equal(feature.required_samples(times, np.full(12,-1), False), [])

    def test_visible_image_can_rescue_missing_torso_and_context_respects_gaps(self):
        body = np.full((7,340),np.nan); body_u = np.zeros(7,bool)
        rgb = np.ones((7,512)); rgb[3] = np.nan
        x,u = feature.fusion_features(body, body_u, rgb, np.arange(7)*.12)
        self.assertEqual(x.shape, (7,2900))
        np.testing.assert_array_equal(u,[True,True,True,False,True,True,True])
        self.assertTrue(np.isnan(x[2,340+3*512:340+4*512]).all())
        self.assertTrue(np.isfinite(x[2,340+2*512:340+3*512]).all())

    def test_missing_rgb_allows_unchanged_body_fallback(self):
        body = np.ones((4,340)); rgb = np.full((4,512),np.nan)
        x,u = feature.fusion_features(body, np.ones(4,bool), rgb, np.arange(4)*.12)
        self.assertTrue(u.all()); self.assertTrue(np.isnan(x[:,340:]).all())
        np.testing.assert_array_equal(x[:,:340],body)

    def test_partial_nonfinite_image_vector_is_rejected(self):
        rgb = np.ones((3,512)); rgb[0,0] = np.nan
        with self.assertRaises(ValueError):
            feature.fusion_features(np.ones((3,340)),np.ones(3,bool),rgb,np.arange(3)*.12)

    def test_source_frame_pts_adapter_is_explicit_and_bounded(self):
        p = np.array([0,.02,.04,.06]); i = np.array([0,2])
        self.assertAlmostEqual(feature.check_times(i,[0,.0401],p,'fullPrograms'),.0001)
        with self.assertRaises(ValueError): feature.check_times(i,[0,.0401],p,'personalShort')
        with self.assertRaises(ValueError): feature.check_times(i,[0,.05],p,'fullPrograms')


if __name__ == '__main__': unittest.main()
