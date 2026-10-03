"""Portable CPU2/1 local-only YOLOX/RTMW and unchanged tracking/normalization."""
import math
from pathlib import Path
from support import SCRIPTS, asset_path
from rtmpose_adapter import normalize_coco, select_bbox
FEET=('left_big_toe','left_small_toe','left_heel','right_big_toe','right_small_toe','right_heel')


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
 DETECTOR=asset_path(config,recipe["checkpoints"]["detector"]["path"])
 POSE=asset_path(config,recipe["checkpoints"]["pose"]["path"])
 import cv2,onnxruntime as ort
 from rtmlib import YOLOX,RTMPose
 for p in (DETECTOR,POSE):
  if not p.is_file():raise ValueError(f'Required local checkpoint absent: {p}; no automatic download')
 cv2.setNumThreads(2)
 # rtmlib does not expose session options. Scope factory override to construction,
 # then restore; all resulting sessions retain explicit2/1threadlimits.
 original=ort.InferenceSession
 def limited(*args,**kwargs):
  options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1;kwargs['sess_options']=options
  return original(*args,**kwargs)
 ort.InferenceSession=limited
 try:
  detector=None if pose_only else YOLOX(str(DETECTOR),backend='onnxruntime',device='cpu');pose=RTMPose(str(POSE),model_input_size=(288,384),backend='onnxruntime',device='cpu',to_openpose=False)
 finally:ort.InferenceSession=original
 return detector,pose
