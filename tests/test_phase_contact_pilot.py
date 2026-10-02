import sys,unittest,copy
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from phase_contact_pilot import decode,pose_features
class ContactTests(unittest.TestCase):
 def test_ordered_decoding(self):
  p=np.array([[.9,.05,.05]]*3+[[.05,.9,.05]]*4+[[.05,.05,.9]]*3)
  self.assertEqual(decode(p),(2,7))
 def test_no_time_frame_contact_identity_features(self):
  points=[dict(name=n,x=x,y=y,confidence=1) for n,x,y in [('left_hip',.4,.5),('right_hip',.6,.5),('left_shoulder',.4,.2),('right_shoulder',.6,.2),('left_knee',.4,.7),('right_knee',.6,.7),('left_ankle',.4,.9),('right_ankle',.6,.9)]]
  pose=dict(coordinateSpace=dict(width=100,height=100),frames=[dict(frameIndex=i,time=i/50,landmarks=copy.deepcopy(points)) for i in range(4)])
  x=pose_features(pose);pose['videoId']='SECRET';pose['lastContact']=999
  for f in pose['frames']:
   f['time']+=999;f['frameIndex']+=999
   for p in f['landmarks']:p['x']=p['x']*.5+.1;p['y']=p['y']*.5+.1
  self.assertTrue(np.allclose(x,pose_features(pose),equal_nan=True))
if __name__=='__main__':unittest.main()
