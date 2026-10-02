"""Map native pose into the verified runtime 50 Hz source-frame timeline."""
import numpy as np

def resample_native(points,scores,indices,pose):
 p=np.asarray(points);s=np.asarray(scores);indices=np.asarray(indices)
 if p.ndim!=3 or p.shape[1:]!=(17,2) or s.shape!=p.shape[:2] or len(p)<3:
  raise ValueError('Expected native COCO17 pose')
 if not np.array_equal(indices,np.arange(len(p))) or pose.get('fps')!=50 or pose.get('timing',{}).get('originalFrameCount')!=len(p):
  raise ValueError('Source decode count or timebase mismatch')
 rows=pose.get('frames',[])
 if len(rows)<3:raise ValueError('Insufficient timeline')
 selected=[];previous=None
 for i,r in enumerate(rows):
  k=r.get('sourceFrameIndex');t=r.get('sourceTime')
  if type(k) is not int or not 0<=k<len(p) or not isinstance(t,(float,int)) or not np.isfinite(t):raise ValueError('Invalid source mapping')
  if r.get('frameIndex')!=i or not isinstance(r.get('time'),(float,int)) or not np.isclose(r['time'],i/50,atol=1e-8,rtol=0):raise ValueError('Nonuniform runtime timeline')
  if previous is not None:
   pk,pt=previous
   if k<pk or (k==pk and t!=pt) or (k>pk and t<=pt):raise ValueError('Inconsistent source presentation order')
  selected.append(k);previous=(k,t)
 return p[selected].copy(),s[selected].copy()
