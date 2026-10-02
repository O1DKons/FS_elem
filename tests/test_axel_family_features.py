import sys
import unittest
from pathlib import Path
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import axel_family


class FamilyFeaturesTests(unittest.TestCase):
    def test_approach_flight_landing_order_is_preserved(self):
        times=np.arange(-.6,.7,.1);body=np.tile(times[:,None],(1,68));usable=np.ones(len(times),bool)
        x= axel_family.segment_features(body,times,usable,0.,.4)
        self.assertEqual(x.shape,(545,))
        self.assertLess(x[0],x[7*68])
        self.assertAlmostEqual(x[-1],.4)

    def test_missing_approach_does_not_become_zero_pose(self):
        times=np.array([0.,.1,.2]);body=np.ones((3,68));usable=np.ones(3,bool)
        x=axel_family.segment_features(body,times,usable,0.,.2)
        self.assertTrue(np.isnan(x[:68]).all())
        self.assertEqual(x[-1],.2)

    def test_incompatible_dense_weights_rejected(self):
        with self.assertRaises(ValueError):
            axel_family.dense_features({'weightsSha256':'wrong','frames':{}},0.,.2)

    def test_noncontiguous_dense_frames_rejected(self):
        with self.assertRaises(ValueError):
            axel_family.dense_features({'weightsSha256':axel_family.RTMW_WEIGHTS,'fps':50.,
                                        'frames':{'1':{},'3':{},'4':{}}},0.,.2)


if __name__=='__main__':unittest.main()
