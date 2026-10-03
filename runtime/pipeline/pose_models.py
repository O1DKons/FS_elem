"""Recipe-bound CPU YOLOX/RTMW and unchanged tracking/normalization."""
import math
from pathlib import Path
from support import SCRIPTS, asset_path
from rtmpose_adapter import normalize_coco, select_bbox
FEET=('left_big_toe','left_small_toe','left_heel','right_big_toe','right_small_toe','right_heel')

def ort_threads(recipe):
 policy=recipe.get('ortThreads',dict(intraOpNumThreads=2,interOpNumThreads=1))
 if (not isinstance(policy,dict) or set(policy)!={'intraOpNumThreads','interOpNumThreads'}
     or type(policy['intraOpNumThreads']) is not int or policy['intraOpNumThreads'] not in (2,4)
     or type(policy['interOpNumThreads']) is not int or policy['interOpNumThreads']!=1):
  raise ValueError('Expected explicit ORT CPU2/1 or4/1 policy')
 return dict(policy)

def runtime_sessions(detector,pose):
 return [model._fs_elem_session_info for model in (detector,pose) if model is not None]

def validate_runtime_sessions(records,recipe,required=True):
 policy=ort_threads(recipe)
 expected=[dict(role=role,**policy,providers=['CPUExecutionProvider']) for role in ('detector','pose')] if required else []
 if records!=expected:raise ValueError('Saved actual ORT session policy differs from recipe')


def track_box(boxes,previous):
 valid=[list(map(float,b[:4])) for b in boxes if len(b)>=4 and all(math.isfinite(float(v)) for v in b[:4]) and b[2]>b[0] and b[3]>b[1]]
 if previous is None:return select_bbox(valid)
 def overlap(b):
  intersection=max(0,min(b[2],previous[2])-max(b[0],previous[0]))*max(0,min(b[3],previous[3])-max(b[1],previous[1]))
  return intersection/((b[2]-b[0])*(b[3]-b[1])+(previous[2]-previous[0])*(previous[3]-previous[1])-intersection)
 good=[b for b in valid if overlap(b)>.05]
 return max(good,key=overlap) if good else None

def normalize_wholebody(points,scores,width,height):
 result=normalize_coco(points[:17],scores[:17],width,height,score_kind='heatmap_peak')
 for name,p,s in zip(FEET,points[17:23],scores[17:23]):
  x,y=float(p[0])/width,float(p[1])/height;s=float(s)
  if all(math.isfinite(v) for v in (x,y,s)) and 0<=x<=1 and 0<=y<=1:result.append(dict(name=name,x=x,y=y,confidence=max(0.,min(1.,s))))
 return result

def models(config, recipe, pose_only=False):
 policy=ort_threads(recipe)
 DETECTOR=asset_path(config,recipe["checkpoints"]["detector"]["path"])
 POSE=asset_path(config,recipe["checkpoints"]["pose"]["path"])
 import cv2,onnxruntime as ort
 from rtmlib import YOLOX,RTMPose
 for p in (DETECTOR,POSE):
  if not p.is_file():raise ValueError(f'Required local checkpoint absent: {p}; no automatic download')
 cv2.setNumThreads(2)
 # rtmlib does not expose session options. Scope factory override to construction,
 # then restore. Verify actual options before any inference.
 original=ort.InferenceSession
 records=[]
 def limited(*args,**kwargs):
  options=ort.SessionOptions();options.intra_op_num_threads=policy['intraOpNumThreads'];options.inter_op_num_threads=1;kwargs['sess_options']=options
  session=original(*args,**kwargs);actual=session.get_session_options();providers=list(session.get_providers())
  if (actual.intra_op_num_threads!=policy['intraOpNumThreads'] or actual.inter_op_num_threads!=1
      or providers!=['CPUExecutionProvider']):raise ValueError('Actual ORT CPU session differs from recipe')
  records.append(dict(**policy,providers=providers))
  return session
 ort.InferenceSession=limited
 try:
  detector=None if pose_only else YOLOX(str(DETECTOR),backend='onnxruntime',device='cpu');pose=RTMPose(str(POSE),model_input_size=(288,384),backend='onnxruntime',device='cpu',to_openpose=False)
 finally:ort.InferenceSession=original
 objects=[('pose',pose)] if pose_only else [('detector',detector),('pose',pose)]
 if len(records)!=len(objects):raise ValueError('Unexpected number of model sessions')
 for (role,model),record in zip(objects,records):model._fs_elem_session_info=dict(role=role,**record)
 return detector,pose
