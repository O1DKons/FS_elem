import sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from binary_pivot import pivot_features

def item(angles,indices=None):
 indices=range(len(angles)) if indices is None else indices
 return dict(firstContact=100,frames=[dict(frameIndex=100+i,candidates=[dict(side='landing',status='visible',heel=[0,0],toe=[np.cos(a),np.sin(a)])]) for i,a in zip(indices,angles)])
class PivotTests(unittest.TestCase):
 def test_rotation_translation_scale_invariant(self):
  a=item([0,.1,.2,.4]);expected=pivot_features(a)
  theta=.7;r=np.array([[np.cos(theta),-np.sin(theta)],[np.sin(theta),np.cos(theta)]])
  for f in a['frames']:
   for c in f['candidates']:
    for key in ('heel','toe'):c[key]=(np.asarray(c[key])@r.T*4+[100,50]).tolist()
  self.assertTrue(np.allclose(expected,pivot_features(a),equal_nan=True))
 def test_missing_frames_never_bridge_and_wrap_is_shortest(self):
  a=item([3.1,-3.1],[0,2]);self.assertTrue(np.isnan(pivot_features(a)[2]));self.assertEqual(pivot_features(a)[1],0)
  b=item([3.1,-3.1]);self.assertAlmostEqual(pivot_features(b)[2],2*np.pi-6.2)
if __name__=='__main__':unittest.main()
