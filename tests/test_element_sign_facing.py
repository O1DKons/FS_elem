import sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from element_sign_facing import facing_features
class Tests(unittest.TestCase):
 def test_missing(self):
  self.assertTrue(np.isnan(facing_features(dict(coordinateSpace=dict(width=100,height=100),frames=[]),dict(firstContact=20,frames=[]))).all())
 def test_translation_and_no_fabricated_face(self):
  pts=[dict(name=n,x=x,y=y,confidence=1) for n,x,y in [('nose',.55,.1),('left_shoulder',.4,.3),('right_shoulder',.6,.3),('left_hip',.4,.6),('right_hip',.6,.6)]]
  p=dict(coordinateSpace=dict(width=100,height=100),frames=[dict(frameIndex=20,landmarks=pts)])
  item=dict(firstContact=20,frames=[dict(frameIndex=20,candidates=[dict(side='landing',status='visible',heel=[40,80],toe=[60,80])])])
  a=facing_features(p,item)
  self.assertEqual(len(a),28)
  for pt in pts:pt['x']+=.1;pt['y']+=.1
  np.testing.assert_allclose(a,facing_features(p,item),equal_nan=True)
  pts[0]['confidence']=.1
  self.assertTrue(np.isnan(facing_features(p,item)[12:14]).all())
