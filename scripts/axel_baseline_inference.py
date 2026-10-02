"""Frozen baseline inference helpers; no training, annotation access or AST loading."""
import numpy as np
from axel_features import flight_context_features
from run_rotation_proxy_baseline import transform
from video_native_type import native_features
from video_type_model import score_classifier

def compatible_nominal_pose(provenance,expected):
 if not expected.get('pose_sha256') or provenance.get('pose_sha256')!=expected['pose_sha256']:
  raise ValueError('Nominal pose weights incompatible with training')

def gated_intervals(times,local,full):
 sets=[]
 for probability in [local,full]:
  e=np.diff(np.r_[False,probability>.5,False].astype(int))
  sets.append([(float(times[i]),float(times[j-1])) for i,j in zip(np.flatnonzero(e==1),np.flatnonzero(e==-1)) if j-i>=2])
 def iou(x,y):return max(0,min(x[1],y[1])-max(x[0],y[0]))/(max(x[1],y[1])-min(x[0],y[0]))
 used=set();usedg=set();selected=[]
 for _,i,j in sorted((-iou(x,y),i,j) for i,x in enumerate(sets[0]) for j,y in enumerate(sets[1]) if iou(x,y)>=.3):
  if i not in used and j not in usedg:used.add(i);usedg.add(j);selected.append(sets[0][i])
 return sorted(selected)

def infer_family(points,scores,fps,indices,flight_models,family):
 x=flight_context_features(points,scores,fps);times=indices/fps;prob=[]
 for model in flight_models:
  prob.append(model['model'].predict_proba(transform(x,model['state']))[:,list(model['model'].classes_).index(1)])
 events=[]
 for start,end in gated_intervals(times,*prob):
  lo=max(0,int(np.floor((start-.6)*fps)));hi=min(len(points),int(np.ceil((end+.3)*fps))+1)
  f,details=native_features(points[lo:hi],scores[lo:hi],fps,indices[lo:hi])
  label='abstain' if f is None else str(family['classes'][score_classifier(family,f[None])[0].argmax()])
  events.append(dict(startSeconds=start,endSeconds=end,family=label,nominal=None,underrotation=None,nominalReason='requires_compatible_rtmw_pose' if label=='axel' else 'not_classified_as_axel'))
 return events
