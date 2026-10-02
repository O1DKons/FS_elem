"""Native RTMPose extractor, preserving the frozen baseline function verbatim.

Complete-video coverage is checked by the consuming runtime's strict contract.
"""
import os,sys,json,hashlib,inspect,math
from pathlib import Path
import numpy as np
os.environ['OMP_NUM_THREADS']='2';os.environ['OPENBLAS_NUM_THREADS']='2'
from video_pose_type import model_and_provenance
from video_type_model import sha
def extract(video,cache):
 import cv2
 body,base=model_and_provenance();digest=sha(video);cache.mkdir(parents=True,exist_ok=True);target=cache/(digest+'.npz')
 contract=dict(base,recordingMode="full-program-native-v1",native_extraction_sha256=hashlib.sha256(inspect.getsource(extract).encode()).hexdigest(),sampling='every decoded source frame; nominal FPS timestamps; no uniform32 reduction',detectorHz=8)
 if target.exists():
  with np.load(target,allow_pickle=False) as d:
   if json.loads(str(d['provenance']))==contract and str(d['source_sha256'])==digest:return target
  raise ValueError('Stale dense cache; choose a new cache directory')
 cap=cv2.VideoCapture(str(video));count=int(cap.get(cv2.CAP_PROP_FRAME_COUNT));fps=float(cap.get(cv2.CAP_PROP_FPS))
 if count<1 or not math.isfinite(fps) or fps<=0:cap.release();raise ValueError('Invalid clip metadata')
 points=[];scores=[];box=None;cadence=max(1,round(fps/8));last_pixels=None;last_detection=-100
 try:
  for n in range(count):
   ok,image=cap.read()
   if not ok:raise ValueError('Incomplete sequential decode')
   pixels=hashlib.sha256(image.tobytes()).hexdigest()
   if pixels==last_pixels:
    points.append(points[-1].copy());scores.append(scores[-1].copy());continue
   last_pixels=pixels
   h,w=image.shape[:2];p=np.full((17,2),np.nan);s=np.zeros(17)
   if n-last_detection>=cadence or box is None:
    last_detection=n
    detections=[np.asarray(b[:4],float) for b in body.det_model(image) if len(b)>=4 and b[2]>b[0] and b[3]>b[1]]
    if detections:
     center=None if box is None else (box[:2]+box[2:])/2
     box=max(detections,key=lambda b:(b[2]-b[0])*(b[3]-b[1])) if center is None else min(detections,key=lambda b:np.linalg.norm((b[:2]+b[2:])/2-center))
    else:box=None
   if box is not None:
    kp,sc=body.pose_model(image,bboxes=[box.tolist()]);p=kp[0,:17];s=sc[0,:17]
    valid=(s>=.3)&np.isfinite(p).all(axis=1)
    if sum(valid)>=8:
     low=p[valid].min(axis=0);high=p[valid].max(axis=0);padding=np.maximum((high-low)*.25,10);box=np.r_[np.maximum(low-padding,0),np.minimum(high+padding,[w-1,h-1])]
   points.append(p);scores.append(s)
 finally:cap.release()
 if sha(video)!=digest:raise ValueError('Video changed during extraction')
 temp=target.with_suffix('.tmp.npz');np.savez_compressed(temp,points=np.array(points),scores=np.array(scores),frame_indices=np.arange(count),times=np.arange(count)/fps,fps=fps,source_sha256=digest,provenance=json.dumps(contract));temp.replace(target);return target

if __name__=='__main__':
 import argparse
 parser=argparse.ArgumentParser();parser.add_argument('video',type=Path);parser.add_argument('cache',type=Path);a=parser.parse_args()
 out=extract(a.video,a.cache)
 print(json.dumps({'path':str(out),'sha256':sha(out),'consumerValidationRequired':True}),flush=True)
