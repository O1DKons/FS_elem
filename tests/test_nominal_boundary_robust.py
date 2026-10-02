import sys
import unittest
from pathlib import Path
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import axel_nominal_robust as robust


class RobustNominalTests(unittest.TestCase):
    def test_replicating_an_event_does_not_increase_its_weight(self):
        x=np.array([[1.,2.],[1.2,3.],[3.,4.],[3.5,5.]])
        y=np.array(['1A','1A','2A','2A'])
        base=robust.fit_weighted_ridge(x,y,np.ones(4))
        copies=robust.fit_weighted_ridge(np.repeat(x,5,axis=0),np.repeat(y,5),np.full(20,.2))
        np.testing.assert_allclose(robust.scores(base,x),robust.scores(copies,x),atol=1e-10)

    def test_fixed_offsets_do_not_select_an_offset_from_the_prediction(self):
        self.assertEqual(len(robust.boundary_windows(100,120)),25)
        self.assertIn((96,124),robust.boundary_windows(100,120))

    def test_disagreement_is_an_abstention(self):
        result=robust.consensus(['1A','2A','1A'])
        self.assertIsNone(result['nominal'])
        self.assertEqual(result['reason'],'boundary_disagreement')

    def test_missing_window_is_not_silently_ignored(self):
        result=robust.consensus(['2A',None,'2A'])
        self.assertIsNone(result['nominal'])
        self.assertEqual(result['reason'],'insufficient_window_coverage')

    def test_empty_hips_keep_duration_but_are_not_hidden(self):
        x,quality=robust.window_features({},100,120,50.)
        self.assertAlmostEqual(x[0],.4)
        self.assertTrue(np.isnan(x[1:]).all())
        self.assertEqual(quality['missingSourceFrames'],19)
        self.assertEqual(quality['usableHipFrames'],0)

    def test_invalid_contact_order_rejected(self):
        with self.assertRaises(ValueError):robust.window_features({},120,100,50.)

    def test_negative_sample_weight_rejected(self):
        with self.assertRaises(ValueError):
            robust.fit_weighted_ridge(np.ones((2,1)),np.array(['1A','2A']),np.array([1.,-1.]))


if __name__=='__main__':unittest.main()
