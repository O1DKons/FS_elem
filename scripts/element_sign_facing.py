"""Head/torso and skate/torso image relations; NOT a front/back detector."""
import numpy as np
from element_sign_sequence import OFFSETS
def facing_features(pose,item):
 frames={f['frameIndex']:f for f in pose['frames']}
 boots={f['frameIndex']:f for f in item['frames']}
 scale=np.array([pose['coordinateSpace']['width'],pose['coordinateSpace']['height']])
 out=[]
 for offset in OFFSETS:
  n=item['firstContact']+offset
  points={p['name']:np.array([p['x'],p['y']])*scale for p in frames.get(n,{}).get('landmarks',[]) if p.get('confidence',0)>=.5 and np.isfinite([p['x'],p['y']]).all() and 0<=p['x']<=1 and 0<=p['y']<=1}
  names=['left_shoulder','right_shoulder','left_hip','right_hip']
  if not all(k in points for k in names):out.extend([np.nan]*4);continue
  shoulder=(points[names[0]]+points[names[1]])/2
  hip=(points[names[2]]+points[names[3]])/2
  torso=shoulder-hip;length=np.linalg.norm(torso)
  if length<3:out.extend([np.nan]*4);continue
  up=torso/length;side=np.array([-up[1],up[0]])
  nose=points.get('nose')
  out.extend([float(np.dot(nose-shoulder,side)/length),float(np.dot(nose-shoulder,up)/length)] if nose is not None else [np.nan]*2)
  c=next((c for c in boots.get(n,{}).get('candidates',[]) if c['side']=='landing' and c['status']=='visible'),None)
  if not c:out.extend([np.nan]*2);continue
  v=np.array(c['toe'])-np.array(c['heel']);span=np.linalg.norm(v)
  out.extend([float(np.dot(v/ span,side)),float(np.dot(v/span,up))] if span>=3 else [np.nan]*2)
 return np.array(out)
