import sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from axel_features import spectrum,flight_context_features,feature_contract
class FeatureTests(unittest.TestCase):
 def test_rotation(self):
  x=np.sin(np.linspace(0,2*np.pi,32,endpoint=False)*3)
  self.assertEqual(spectrum(x)[:10].argmax(),2)
  np.testing.assert_allclose(spectrum(x),spectrum(x+200),atol=1e-10)
 def test_missing(self):
  for x in [[],[1,2,3],[np.nan]*20]:self.assertTrue(np.isnan(spectrum(x)).all())
 def test_constant(self):np.testing.assert_array_equal(spectrum(np.ones(20)),np.zeros(20))
 def test_context(self):
  p=np.ones((40,17,2));s=np.ones((40,17));p[:,5:7,1]=20
  x=flight_context_features(p,s,50);self.assertEqual(x.shape,(40,340));self.assertTrue(np.isnan(x[:10,:68]).all());self.assertTrue(np.isnan(x[-10:,-68:]).all())
 def test_contract(self):self.assertEqual(len(feature_contract()['codeSha256']),64)
if __name__=='__main__':unittest.main()
