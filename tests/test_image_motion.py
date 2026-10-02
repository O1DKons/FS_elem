import sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from image_motion import describe_flow,pool_motion
class MotionTests(unittest.TestCase):
 def test_uniform_translation_is_removed(self):
  flow=np.zeros((40,60,2),np.float32);flow[:]=[5,-3]
  np.testing.assert_allclose(describe_flow(flow,[10,5,50,35],.02),[0,0,0],atol=1e-6)
 def test_motion_scales_with_time_and_body_size(self):
  flow=np.zeros((40,60,2),np.float32);flow[:,30:,0]=2
  a=describe_flow(flow,[10,5,50,35],.02);b=describe_flow(flow*2,[10,5,50,35],.04)
  np.testing.assert_allclose(a,b);self.assertGreater(a[0],0)
 def test_pool_uses_fixed_contact_relative_intervals_only(self):
  rows=[dict(frameIndex=n,values=[n,n,n]) for n in range(30)]
  f=pool_motion(rows,10,15)
  changed=[dict(frameIndex=r['frameIndex'],values=[999]*3) if r['frameIndex']<=10 or r['frameIndex']>25 else r for r in rows]
  np.testing.assert_allclose(f,pool_motion(changed,10,15))
  self.assertEqual(len(f),12)
 def test_invalid_time_rejected(self):
  with self.assertRaises(ValueError):describe_flow(np.zeros((2,2,2)),[0,0,2,2],0)
if __name__=='__main__':unittest.main()
