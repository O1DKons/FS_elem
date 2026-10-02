"""Side-swap invariant 2D spans in flight and landing, not 3D angles."""
import numpy as np
from run_rotation_proxy_baseline import extract_features
def pose_features(pose,item):
 out=[]
 for lo,hi in [(item['lastContact'],item['firstContact']),(item['firstContact']-1,item['firstContact']+11)]:
  values,_=extract_features(pose,dict(lastContact=dict(frameIndex=lo,time=lo/50),firstContact=dict(frameIndex=hi,time=hi/50)))
  out.extend(values[1:]) # Exclude manually supplied duration.
 return np.array(out)
