import sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from run_facing_image import descriptor
class Tests(unittest.TestCase):
 def test_missing_torso_abstains(self):
  self.assertEqual(descriptor(np.zeros((100,100),dtype=np.uint8),[]),(None,None))
 def test_constant_crop_finite_and_no_mutation(self):
  image=np.zeros((200,200),dtype=np.uint8)
  points=[dict(name=n,x=x,y=y,confidence=1) for n,x,y in [('left_shoulder',.4,.3),('right_shoulder',.6,.3),('left_hip',.4,.6),('right_hip',.6,.6)]]
  values,box=descriptor(image,points)
  self.assertEqual(len(values),3780);self.assertTrue(np.isfinite(values).all())
  self.assertTrue(all(0<=v<=200 for v in box));self.assertEqual(image.sum(),0)
