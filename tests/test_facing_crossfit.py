import sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from facing_crossfit import predict_facing
class CrossfitTest(unittest.TestCase):
 def test_excluded_athlete_labels_cannot_change_prediction(self):
  x=np.array([[0.,0.],[1.,1.],[100.,100.]])
  y=np.array(['front','back','front']);groups=np.array(['a','b','held'])
  p,used=predict_facing(x,y,groups,np.array([[.1,.1]]),{'held'})
  y[2]='back';q,_=predict_facing(x,y,groups,np.array([[.1,.1]]),{'held'})
  np.testing.assert_array_equal(p,q);self.assertEqual(used,[0,1])
 def test_absent_classes_and_missing_query(self):
  p,_=predict_facing(np.array([[1.,1.]]),np.array(['side']),np.array(['a']),np.array([[1.,1.],[np.nan,1.]]),set())
  np.testing.assert_array_equal(p[0],[0,0,1]);self.assertTrue(np.isnan(p[1]).all())
if __name__=='__main__':unittest.main()
