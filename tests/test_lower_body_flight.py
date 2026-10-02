import importlib.util
from pathlib import Path
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / 'work/lower-body-flight-v1/lower_body.py'
module = None
if path.exists():
    spec = importlib.util.spec_from_file_location('lower_body_flight_probe', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)


def legs(n):
    points = np.tile(np.array([[40,40],[60,40],[40,80],[60,80],
                              [40,120],[60,120],[45,125],[65,125],
                              [38,123],[58,123]], float), (n,1,1))
    return points, np.ones((n,10))


class LowerBodyFlightTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(module, 'Shoulder-independent lower-body representation missing')
        self.times = np.array([0., .1, .21, .34, .46, .58, .71])

    def test_visible_legs_do_not_require_shoulders(self):
        p,s = legs(len(self.times))
        x,u = module.leg_features(p,s,self.times)
        self.assertEqual(x.shape,(7,40))
        self.assertTrue(u.all())
        self.assertTrue(np.isfinite(x).all())
        self.assertNotIn('left_shoulder',module.NAMES)

    def test_translation_and_uniform_image_scale_leave_features_unchanged(self):
        p,s = legs(len(self.times))
        p[:,6,0] += self.times**2*10
        x,u = module.leg_features(p,s,self.times)
        actual,au = module.leg_features(p*3+np.array([700,-120]),s,self.times)
        np.testing.assert_allclose(actual,x,rtol=0,atol=1e-13)
        np.testing.assert_array_equal(au,u)

    def test_derivatives_follow_real_nonuniform_times(self):
        p,s = legs(len(self.times));p[:,6,0] += self.times**2*80
        x,u = module.leg_features(p,s,self.times)
        self.assertAlmostEqual(x[3,20+12],2*self.times[3])

    def test_missing_ankle_is_not_filled_and_other_leg_can_supply_scale(self):
        p,s = legs(len(self.times));s[3,4] = 0
        x,u = module.leg_features(p,s,self.times)
        self.assertTrue(u[3])
        self.assertTrue(np.isnan(x[3,8:10]).all())
        self.assertTrue(np.isnan(x[3,28:30]).all())

    def test_missing_hip_or_both_complete_legs_disables_center(self):
        p,s = legs(len(self.times));s[2,0] = 0;s[4,2:4] = 0
        x,u = module.leg_features(p,s,self.times)
        self.assertFalse(u[2]);self.assertFalse(u[4])
        self.assertTrue(np.isnan(x[[2,4]]).all())

    def test_derivative_never_bridges_long_gap_or_missing_center(self):
        times = np.array([0.,.1,.2,.6,.7,.8])
        p,s = legs(len(times));p[3:,6,0] += 400
        x,u = module.leg_features(p,s,times)
        np.testing.assert_allclose(x[:,32],0.,rtol=0,atol=0)
        p,s = legs(7);s[3,0] = 0;p[4:,6,0] += 400
        x,u = module.leg_features(p,s,self.times)
        np.testing.assert_allclose(x[[0,1,2,4,5,6],32],0.,rtol=0,atol=0)

    def test_invalid_or_duplicate_source_times_rejected(self):
        p,s = legs(7)
        for times in (np.zeros(7), np.array([0,.1,.2,np.nan,.4,.5,.6])):
            with self.assertRaises(ValueError):module.leg_features(p,s,times)

    def test_left_and_right_channels_never_sorted_by_image_position(self):
        p,s = legs(7);p[:,6,0] = 90;p[:,7,0] = 10
        x,u = module.leg_features(p,s,self.times)
        self.assertGreater(x[3,12],x[3,14])


if __name__ == '__main__':
    unittest.main()
