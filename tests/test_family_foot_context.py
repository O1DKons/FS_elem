import importlib.util
from pathlib import Path
import sys
import unittest
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import axel_family
path=ROOT/'work/family-foot-context-v1/features.py'
if path.exists():
    spec=importlib.util.spec_from_file_location('foot_family_context_features',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
else:module=None

class FootContextTests(unittest.TestCase):
    def setUp(self):self.assertIsNotNone(module,'Foot family context is missing')

    def test_existing_body_feature_vector_stays_exactly_equal(self):
        times=np.arange(-.6,.8,.1);x=np.tile(times[:,None],(1,92));usable=np.ones(len(times),bool)
        result=module.segment_features(x,times,usable,0.,.4)
        self.assertEqual(result.shape,(737,))
        np.testing.assert_equal(result[:545],axel_family.segment_features(x[:,:68],times,usable,0.,.4))

    def test_foot_position_and_velocity_channels_keep_temporal_order(self):
        times=np.arange(-.6,.8,.1);x=np.zeros((len(times),92));x[:,68:]=times[:,None]
        result=module.segment_features(x,times,np.ones(len(times),bool),0.,.4)
        self.assertLess(result[545],result[545+7*24])
        self.assertAlmostEqual(result[545],-.55)

    def test_unknown_foot_and_missing_approach_do_not_become_zero(self):
        times=np.array([0.,.1,.2]);x=np.ones((3,92));x[:,68]=np.nan
        result=module.segment_features(x,times,np.ones(3,bool),0.,.2)
        self.assertTrue(np.isnan(result[545:569]).all())
        self.assertTrue(np.isnan(result[545::24]).all())

    def test_unusable_frame_cannot_supply_foot_evidence(self):
        times=np.array([0.,.1,.2]);x=np.ones((3,92));x[0,68:]=999
        result=module.segment_features(x,times,np.array([False,True,True]),0.,.2)
        finite=result[545:][np.isfinite(result[545:])]
        self.assertTrue((finite==1).all())

    def test_wrong_channel_count_or_pose_weights_is_rejected(self):
        with self.assertRaises(ValueError):
            module.segment_features(np.ones((3,68)),np.array([0.,.1,.2]),np.ones(3,bool),0.,.2)
        with self.assertRaises(ValueError):module.pose_features({'model':{'poseSha256':'wrong'}})

if __name__=='__main__':unittest.main()
