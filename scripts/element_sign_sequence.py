"""Ordered image-plane shoulder/hip axis samples, not physical yaw angles."""
import numpy as np
OFFSETS=(-12,-8,-4,0,2,4,8)
def sequence_features(pose,item):
 frames={f['frameIndex']:f for f in pose['frames']}
 scale=np.array([pose['coordinateSpace']['width'],pose['coordinateSpace']['height']])
 out=[]
 for offset in OFFSETS:
  f=frames.get(item['firstContact']+offset,{})
  points={p['name']:np.array([p['x'],p['y']])*scale for p in f.get('landmarks',[]) if p.get('confidence',0)>=.5 and np.isfinite([p['x'],p['y']]).all() and 0<=p['x']<=1 and 0<=p['y']<=1}
  for part in ('shoulder','hip'):
   a,b=points.get('left_'+part),points.get('right_'+part)
   if a is None or b is None or np.linalg.norm(b-a)<3:out.extend([np.nan,np.nan]);continue
   x,y=(b-a)/np.linalg.norm(b-a)
   out.extend([x*x-y*y,2*x*y]) # Undirected axis: immune to left/right swaps.
 return np.array(out)
