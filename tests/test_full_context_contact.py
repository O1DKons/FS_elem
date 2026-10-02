import sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from full_context_contact import features,validate_folds
class FeatureTests(unittest.TestCase):
 def pose(self):
  p=np.ones((10,17,2))*20;p[:,5:7,1]=10;p[:,:,0]+=np.arange(17);s=np.ones((10,17));return p,s
 def test_shape_translation_scale_and_confidence(self):
  p,s=self.pose();a=features(p,s,50);self.assertEqual(a.shape,(10,68));np.testing.assert_allclose(a,features(p*3+100,s,50),atol=1e-12)
  s[:,9]=.1;self.assertTrue(np.isnan(features(p,s,50)[:,18:20]).all())
 def test_derivative_per_second(self):
  p,s=self.pose();p[:,9,0]+=np.arange(10);a=features(p,s,25);b=features(p,s,50);np.testing.assert_allclose(b[:,34:],2*a[:,34:])
 def test_torso_abstention_mask(self):
  p,s=self.pose();p[:,5:7]=p[:,11:13];self.assertTrue(np.isnan(features(p,s,50)).all())
 def test_disjoint_and_complete_folds(self):
  records=[dict(athlete=str(i),videoId=str(i),sourceSha256=str(i)) for i in range(2)];folds=[dict(trainIndices=[1],testIndices=[0]),dict(trainIndices=[0],testIndices=[1])];validate_folds(records,folds)
  records[1]['videoId']='0'
  with self.assertRaises(ValueError):validate_folds(records,folds)
if __name__=='__main__':unittest.main()
