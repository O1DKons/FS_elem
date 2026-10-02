import sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from landing_rotation_model import fit_model,predict_item
class LandingModelTest(unittest.TestCase):
 def test_missing_sequence_abstains_and_wrong_fps_rejected(self):
  model=fit_model(np.array([[0.]*9,[1.]*9]),np.array([0,1]))
  item={'firstContact':1,'frames':[]}
  self.assertEqual(predict_item(item,model,50)['status'],'insufficient_evidence')
  with self.assertRaises(ValueError):predict_item(item,model,30)
 def test_fit_rejects_one_class_and_nonmatching_dimensions(self):
  with self.assertRaises(ValueError):fit_model(np.ones((2,9)),np.array([1,1]))
  with self.assertRaises(ValueError):fit_model(np.ones((2,8)),np.array([0,1]))
if __name__=='__main__':unittest.main()
