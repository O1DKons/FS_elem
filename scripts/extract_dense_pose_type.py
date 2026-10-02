"""Native-frame RTMPose cache for a new temporal experiment; no classifier changes."""
import argparse,hashlib,inspect,json,math,os
os.environ['OMP_NUM_THREADS']='2';os.environ['OPENBLAS_NUM_THREADS']='2'
from pathlib import Path
import numpy as np
from video_pose_type import model_and_provenance
from video_type_model import ROOT,sha

def extract(video,cache):
 import cv2
 body,base=model_and_provenance();digest=sha(video);cache.mkdir(parents=True,exist_ok=True);target=cache/(digest+'.npz')
 contract=dict(base,native_extraction_sha256=hashlib.sha256(inspect.getsource(extract).encode()).hexdigest(),sampling='every decoded source frame; nominal FPS timestamps; no uniform32 reduction',detectorHz=8)
 if target.exists():
  with np.load(target,allow_pickle=False) as d:
   if json.loads(str(d['provenance']))==contract and str(d['source_sha256'])==digest:return target
  raise ValueError('Stale dense cache; choose a new cache directory')
 cap=cv2.VideoCapture(str(video));count=int(cap.get(cv2.CAP_PROP_FRAME_COUNT));fps=float(cap.get(cv2.CAP_PROP_FPS))
 if count<1 or not math.isfinite(fps) or fps<=0 or count/fps>60:cap.release();raise ValueError('Invalid clip metadata')
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

def main():
 p=argparse.ArgumentParser();p.add_argument('--cache',type=Path,default=ROOT/'phase-cache/video-pose-dense-v2');p.add_argument('--limit',type=int);a=p.parse_args()
 manifest=json.loads((ROOT/'data/skatingverse-pilot-v1/manifest.json').read_text());rows=[r for r in manifest['items'] if int(r['label'])!=27]
 if a.limit is not None:rows=rows[:a.limit]
 records=[]
 for i,r in enumerate(rows):
  video=ROOT/'data/skatingverse-pilot-v1'/r['file'];assert sha(video)==r['sha256']
  path=extract(video,a.cache)
  with np.load(path,allow_pickle=False) as d:records.append(dict(sha256=r['sha256'],label=r['label'],group=r['group'],frames=len(d['points']),fps=float(d['fps']),cache=str(path.relative_to(ROOT))))
  out=ROOT/'work/type-sampling-audit/dense-progress.json';out.write_text(json.dumps(dict(records=records,complete=len(records)==len(rows),total=len(rows)),indent=2));print(f'{i+1}/{len(rows)} native frames={records[-1]["frames"]}',flush=True)
if __name__=='__main__':main()
