"""Short-video RTMW proposals. No automatic contact, jump or rotation truth."""
import argparse,bisect,hashlib,json,math,os,time
from pathlib import Path
os.environ['OMP_NUM_THREADS']='2';os.environ['OPENBLAS_NUM_THREADS']='2'
from rtmpose_adapter import normalize_coco,select_bbox
from boot_detection import candidates,temporal_checks,landing_candidates
from source_frame_reuse import SourceFrameCache,source_key
FEET=('left_big_toe','left_small_toe','left_heel','right_big_toe','right_small_toe','right_heel')
CACHE=Path.home()/'.cache/rtmlib/hub/checkpoints'
DETECTOR=CACHE/'yolox_m_8xb8-300e_humanart-c2c7a14a.onnx'
POSE=CACHE/'rtmw-dw-x-l_simcc-cocktail14_270e-384x288_20231122.onnx'
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
 return h.hexdigest()
def sample_timeline(times,fps=50):
 if len(times)<2 or any(not math.isfinite(t) for t in times) or any(b<=a for a,b in zip(times,times[1:])):raise ValueError('Source presentation timestamps must increase strictly')
 duration=times[-1]-times[0]
 if duration>10:raise ValueError('Only short single-element clips up to10seconds supported')
 result=[]
 for n in range(math.floor(duration*fps+1e-7)+1):
  t=times[0]+n/fps;j=bisect.bisect_left(times,t);choices=[k for k in (j-1,j) if 0<=k<len(times)];k=min(choices,key=lambda k:(round(abs(times[k]-t),10),k))
  result.append(dict(frameIndex=n,time=n/fps,sourceFrameIndex=k,sourceTime=times[k]))
 return result

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

def decode(source,out):
 import cv2
 cap=cv2.VideoCapture(str(source))
 if not cap.isOpened():raise ValueError('Cannot decode input video')
 nominal=cap.get(cv2.CAP_PROP_FPS);count=cap.get(cv2.CAP_PROP_FRAME_COUNT)
 if nominal>0 and count/nominal>10.05:cap.release();raise ValueError('Clip exceeds10seconds; provide a short element clip')
 times=[]
 while True:
  ok,im=cap.read()
  if not ok:break
  times.append(cap.get(cv2.CAP_PROP_POS_MSEC)/1000)
  if len(times)>2500 or (len(times)>1 and times[-1]-times[0]>10.05):cap.release();raise ValueError('Clip exceeds resource limit')
 cap.release();timeline=sample_timeline(times);needed={}
 for row in timeline:needed.setdefault(row['sourceFrameIndex'],[]).append(row)
 cap=cv2.VideoCapture(str(source));i=0;framesdir=out/'frames';framesdir.mkdir(exist_ok=True)
 while True:
  ok,im=cap.read()
  if not ok:break
  if i in needed:
   h,w=im.shape[:2];scale=min(1280/w,720/h);nw,nh=round(w*scale),round(h*scale)
   resized=cv2.resize(im,(nw,nh));canvas=cv2.copyMakeBorder(resized,(720-nh)//2,720-nh-(720-nh)//2,(1280-nw)//2,1280-nw-(1280-nw)//2,cv2.BORDER_CONSTANT)
   ok,encoded=cv2.imencode('.png',canvas)
   if not ok:raise ValueError('PNG encoding failed')
   data=encoded.tobytes();digest=hashlib.sha256(data).hexdigest()
   for row in needed[i]:
    name=f"frames/{row['frameIndex']:06d}.png";(out/name).write_bytes(data);row.update(image=name,sourceFrameSha256=digest,sourceImageWidth=w,sourceImageHeight=h,transform=dict(scaleX=nw/w,scaleY=nh/h,padX=(1280-nw)//2,padY=(720-nh)//2))
  i+=1
 cap.release()
 if any('image' not in row for row in timeline):raise ValueError('Second decode did not reproduce required frames')
 return timeline,dict(originalFrameCount=len(times),nominalSourceFps=nominal,presentationStart=times[0],presentationEnd=times[-1],sampling='nearest source presentation timestamp, ties earlier; duplicated samples preserved')

def models(pose_only=False):
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

def run(source,out,first_contact=None):
 source=Path(source).resolve();out=Path(out).resolve()
 if not source.is_file():raise ValueError('Input video missing')
 out.mkdir(parents=True,exist_ok=True)
 if (out/'pose.json').exists():raise ValueError('Output already contains pose.json; use a new directory')
 digest=sha(source);rows,timing=decode(source,out)
 contact=None if first_contact is None else round(first_contact*50)
 if first_contact is not None and (not math.isfinite(first_contact) or first_contact<0 or contact>=len(rows)):raise ValueError('Contact must lie inside clip timeline')
 detector,pose=models();box=None;last_detection=-100;started=time.time()
 body_cache=SourceFrameCache();mirror_cache=SourceFrameCache()
 for row in rows:
  import cv2
  n=row['frameIndex']
  # The closure is never executed for a repeated source observation: no detector,
  # pose crop update, or model noise can turn an identical PNG into motion.
  def infer_body():
   im=cv2.imread(str(out/row['image']));current_box=box;status='pose_tracked'
   detection_due=n-last_detection>=5 or current_box is None
   if detection_due:
    current_box=track_box(detector(im),current_box);status='detected' if current_box is not None else 'missing_detection'
   landmarks=[];raw={};next_box=current_box
   if current_box is not None:
    kp,sc=pose(im,bboxes=[current_box]);points=kp[0,:23].tolist();scores=sc[0,:23].tolist();landmarks=normalize_wholebody(points,scores,1280,720)
    raw=dict(points=points,scores=scores,box=current_box)
    valid=[p for p in landmarks if p['confidence']>=.5]
    if len(valid)>=6:
     xs=[p['x']*1280 for p in valid];ys=[p['y']*720 for p in valid];next_box=[max(0,min(xs)-40),max(0,min(ys)-40),min(1279,max(xs)+40),min(719,max(ys)+40)]
    else:next_box=None;status='insufficient_pose'
   return dict(landmarks=landmarks,raw=raw,nextBox=next_box,trackingStatus=status,detectionAttempted=detection_due)
  body,reused=body_cache.compute(row,infer_body)
  if body['detectionAttempted'] and not reused:last_detection=n
  box=body['nextBox'];raw=body['raw'];feet=[]
  if raw and contact is not None and contact-2<=n<=contact+10:
   def infer_mirror():
    im=cv2.imread(str(out/row['image']));b=raw['box'];flipbox=[1279-b[2],b[1],1279-b[0],b[3]]
    fk,fs=pose(cv2.flip(im,1),bboxes=[flipbox]);return dict(mirrored=fk[0,:23].tolist(),mirrorScores=fs[0,:23].tolist())
   mirrored,_=mirror_cache.compute(row,infer_mirror);raw.update(mirrored)
   feet=candidates(raw['points'],raw['scores'],raw['mirrored'],raw['mirrorScores'],1280,720,raw['box'][3]-raw['box'][1])
  row.update(landmarks=body['landmarks'],candidates=feet,trackingStatus=body['trackingStatus'],raw=raw,sourceObservationReused=reused)
  if (n+1)%25==0:print('LANDMARKS',n+1,'/',len(rows),round(time.time()-started,1),'seconds',flush=True)
 if contact is not None:rows=landing_candidates(temporal_checks(rows),contact)
 if sha(source)!=digest:raise ValueError('Input video changed during analysis')
 result=dict(schemaVersion=1,kind='pose',status='unreviewed_model_proposal',videoId=digest[:16],sourceSha256=digest,sourcePath=str(source),coordinateSpace=dict(type='image-normalized',width=1280,height=720),width=1280,height=720,fps=50,timing=timing,firstContact=contact,contactProvenance='provided_cli_seconds_not_automatically_detected' if contact is not None else 'not_supplied',model=dict(name='RTMW-x WholeBody + YOLOX-m',weightsSha256=sha(POSE),detectorSha256=sha(DETECTOR),device='cpu',intraOpThreads=2,interOpThreads=1),settings=dict(detectorEveryFrames=5,sourceReuse='sourceFrameIndex+PNG SHA; exact body/box/mirror reuse; v1',mirrorScope='provided contact-2..+10 only',sideConvention='raw model anatomical proposals, no identity correction',footDefinition='mean toes and heel, not blade contact',noDetection='empty landmarks; no fullframe fallback'),frames=rows)
 target=out/'pose.json';temp=out/'pose.tmp';temp.write_text(json.dumps(result,allow_nan=False));temp.replace(target)
 print('SAVED',target,flush=True);return result

def augment_contact(out,seconds,boot_output=None):
 import cv2
 out=Path(out).resolve();path=out/'pose.json';data=json.loads(path.read_text());contact=round(seconds*data['fps'])
 if not math.isfinite(seconds) or seconds<0 or not any(f['frameIndex']==contact for f in data['frames']):raise ValueError('Contact outside pose timeline')
 target=Path(boot_output) if boot_output is not None else out/'boot.json'
 if target.exists():raise ValueError('Boot output exists; specify a new --boot-output')
 if sha(Path(data['sourcePath']))!=data['sourceSha256']:raise ValueError('Source changed since pose inference')
 if data['model']['weightsSha256']!=sha(POSE):raise ValueError('Wholebody weights changed since pose inference')
 # Refuse old inconsistent duplicate poses rather than pairing their different
 # original crops with one cached mirrored crop. Re-run dense extraction first.
 observed={}
 for f in data['frames']:
  key=source_key(f);raw=f.get('raw',{})
  signature=json.dumps({k:raw.get(k) for k in ('box','points','scores')},sort_keys=True)
  if key is not None and key in observed and observed[key]!=signature:raise ValueError('Inconsistent duplicate source poses; re-run dense extraction with source reuse')
  if key is not None:observed[key]=signature
 _,model=models(pose_only=True);frames=[];mirror_cache=SourceFrameCache()
 for f in data['frames']:
  if not contact-2<=f['frameIndex']<=contact+10:continue
  image=out/f['image']
  if sha(image)!=f['sourceFrameSha256']:raise ValueError('Standardized frame hash mismatch')
  raw=f.get('raw',{});pred=[]
  if raw:
   def infer_mirror():
    box=raw['box'];im=cv2.imread(str(image));flipbox=[1279-box[2],box[1],1279-box[0],box[3]]
    fk,fs=model(cv2.flip(im,1),bboxes=[flipbox]);return dict(points=fk[0,:23].tolist(),scores=fs[0,:23].tolist())
   mirrored,_=mirror_cache.compute(f,infer_mirror);box=raw['box']
   pred=candidates(raw['points'],raw['scores'],mirrored['points'],mirrored['scores'],1280,720,box[3]-box[1])
  frames.append(dict(frameIndex=f['frameIndex'],time=f['time'],sourceFrameIndex=f['sourceFrameIndex'],sourceTime=f['sourceTime'],image=f['image'],sourceFrameSha256=f['sourceFrameSha256'],candidates=pred))
 frames=landing_candidates(temporal_checks(frames),contact)
 item=dict(attemptId=data['videoId'],sourceSha256=data['sourceSha256'],firstContact=contact,frames=frames)
 result=dict(schemaVersion=1,fps=data['fps'],width=data['width'],height=data['height'],poseSha256=sha(path),contactProvenance='supplied_proposal_seconds_not_ground_truth',status='unreviewed_model_proposal',items=[item])
 target.parent.mkdir(parents=True,exist_ok=True);temp=target.with_suffix('.tmp');temp.write_text(json.dumps(result,allow_nan=False));temp.replace(target);print('SAVED',target,flush=True);return result

def main():
 p=argparse.ArgumentParser();p.add_argument('--video',type=Path);p.add_argument('--output',required=True,type=Path);p.add_argument('--first-contact',type=float);p.add_argument('--augment-contact',type=float);p.add_argument('--boot-output',type=Path);a=p.parse_args()
 if a.augment_contact is not None:
  if a.video is not None or a.first_contact is not None:p.error('--augment-contact uses existing output, without --video/--first-contact')
  augment_contact(a.output,a.augment_contact,a.boot_output)
 else:
  if a.video is None:p.error('--video required for dense inference')
  run(a.video,a.output,a.first_contact)
if __name__=='__main__':main()
