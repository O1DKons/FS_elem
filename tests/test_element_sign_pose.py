import sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from element_sign_pose import pose_features
class Tests(unittest.TestCase):
 def test_geometry_translation_and_side_swap_invariant(self):
  points=[dict(name=n,x=x,y=y,confidence=1) for n,x,y in [('left_shoulder',.4,.2),('right_shoulder',.6,.2),('left_hip',.45,.5),('right_hip',.55,.5),('left_ankle',.4,.8),('right_ankle',.6,.8),('left_wrist',.3,.4),('right_wrist',.7,.4)]]
  pose=dict(coordinateSpace=dict(width=1280,height=720),frames=[dict(frameIndex=n,landmarks=points) for n in range(10,25)])
  item=dict(lastContact=10,firstContact=14)
  a=pose_features(pose,item)
  moved=[dict(p,x=p['x']+.1,y=p['y']+.1,name=p['name'].replace('left','TEMP').replace('right','left').replace('TEMP','right')) for p in points]
  pose['frames']=[dict(frameIndex=n,landmarks=moved) for n in range(10,25)]
  np.testing.assert_allclose(a,pose_features(pose,item))
  self.assertEqual(len(a),16)
 def test_missing_geometry(self):
  a=pose_features(dict(coordinateSpace=dict(width=1280,height=720),frames=[]),dict(lastContact=10,firstContact=14))
  self.assertTrue(np.isnan(a).all())
