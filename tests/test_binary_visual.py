import sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from binary_visual import lower_box,pool,evaluate_visual
class BinaryVisualTests(unittest.TestCase):
 def test_crop_ignores_torso_and_requires_leg_geometry(self):
  names=['left_hip','right_hip','left_knee','right_knee','left_ankle','right_ankle']
  points=[dict(name=n,x=.4+(i%2)*.1,y=.4+(i//2)*.2,confidence=1) for i,n in enumerate(names)]
  box=lower_box(points,1000,1000)
  self.assertEqual(box,lower_box(points+[dict(name='nose',x=1,y=0,confidence=1)],1000,1000))
  self.assertIsNone(lower_box(points[:2],1000,1000))
  self.assertGreaterEqual(box[1],300)
 def test_pool_preserves_order(self):
  a=np.array([[1.,2.],[3.,6.],[5.,10.]])
  self.assertTrue(np.allclose(pool(a),[3,6,4,8]))
  self.assertTrue(np.allclose(pool(a[::-1]),[3,6,-4,-8]))
 def test_held_out_labels_do_not_change_predictions(self):
  x=np.arange(48,dtype=float).reshape(8,6);y=np.array([0,1,0,1,0,1,0,1]);g=np.array(list('aabbccdd'))
  first=evaluate_visual(x,y,g);y[:2]=1-y[:2];second=evaluate_visual(x,y,g)
  self.assertEqual(first['predictions'][:2],second['predictions'][:2])
  self.assertEqual(first['scores'][:2],second['scores'][:2])
if __name__=='__main__':unittest.main()
