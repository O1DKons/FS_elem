import importlib.util
from pathlib import Path
import sys
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from full_context_contact import features as body_features
path = ROOT/'work/flight-image-trajectory-v1/trajectory.py'
if path.exists():
    spec=importlib.util.spec_from_file_location('flight_image_trajectory',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
else: module=None


def skeleton(n):
    p=np.full((n,17,2),100.,float)
    p[:,5:7]=[[80.,100.],[120.,100.]]
    p[:,11:13]=[[90.,200.],[110.,200.]]
    p[:,15:17]=[[90.,300.],[110.,300.]]
    return p,np.ones((n,17))


class ImageTrajectoryTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(module,'Global image motion feature missing')
        self.times=np.array([0.,.1,.21,.34,.46,.58,.71])

    def test_old_geometry_discards_rigid_quadratic_translation_but_new_channels_retain_it(self):
        p,s=skeleton(len(self.times));moving=p.copy();moving[:,:,1]+=self.times[:,None]**2*100
        np.testing.assert_allclose(body_features(p,s,10)[:,:34],body_features(moving,s,10)[:,:34],atol=1e-14)
        x=module.trajectory_features(moving,s,self.times)
        self.assertEqual(x.shape,(7,8))
        self.assertAlmostEqual(x[3,1],2*self.times[3])
        self.assertAlmostEqual(x[3,3],2.)
        self.assertAlmostEqual(x[3,7],2.)

    def test_uniform_image_scale_does_not_change_normalized_motion(self):
        p,s=skeleton(len(self.times));p[:,:,1]+=self.times[:,None]**2*100
        np.testing.assert_allclose(module.trajectory_features(p,s,self.times),
                                   module.trajectory_features(p*2,s,self.times),atol=1e-12)

    def test_timestamp_gap_does_not_create_velocity_across_camera_cut(self):
        times=np.array([0.,.1,.2,.6,.7,.8]);p,s=skeleton(len(times));p[3:]+=1000
        x=module.trajectory_features(p,s,times)
        np.testing.assert_allclose(x,0.,atol=1e-10)

    def test_missing_ankle_does_not_fill_or_bridge_it(self):
        times=np.arange(9)*.1;p,s=skeleton(len(times));s[4,15]=.1;p[5:,15:17]+=500
        x=module.trajectory_features(p,s,times)
        self.assertTrue(np.isnan(x[4,4:]).all())
        np.testing.assert_allclose(x[:4,4:],0.,atol=1e-10)
        np.testing.assert_allclose(x[5:,4:],0.,atol=1e-10)
        self.assertTrue(np.isfinite(x[4,:4]).all())

    def test_missing_torso_preserves_original_visibility_gate(self):
        p,s=skeleton(len(self.times));s[3,5]=.1
        self.assertTrue(np.isnan(module.trajectory_features(p,s,self.times)[3]).all())

    def test_nonmonotonic_pts_rejected(self):
        p,s=skeleton(len(self.times))
        with self.assertRaises(ValueError):module.trajectory_features(p,s,self.times[::-1])


if __name__=='__main__':unittest.main()
