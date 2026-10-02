"""Offline RTMW feet re-detection on existing verified FS_elem source frames.
Run: work/step23-rtmpose/venv/bin/python scripts/run_boot_workbench.py
Does not modify body poses, contact annotations or expert labels.
"""
import argparse,hashlib,json,time,shutil
from pathlib import Path
from boot_detection import candidates, temporal_checks, landing_candidates
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 import cv2
 from rtmlib import RTMPose
 from rtmlib.tools.solution.wholebody import Wholebody
 parser=argparse.ArgumentParser();parser.add_argument('--attempt',action='append');args=parser.parse_args()
 cache=ROOT/'data/boot-rtmw-v1';cache.mkdir(exist_ok=True)
 manifest_path=ROOT/'data/axel-demo-v1/rotation-review-data.json';manifest=json.loads(manifest_path.read_text())
 model=RTMPose(Wholebody.MODE['performance']['pose'],model_input_size=(288,384),backend='onnxruntime',device='cpu',to_openpose=False)
 weights_sha=sha(Path(model.onnx_model));settings=dict(model='RTMW-x WholeBody 384x288 + mirror agreement',weightsSha256=weights_sha,sourceManifestSha256=sha(manifest_path),version=1,gate='score>=.5; span>=max(10,.02bodyHeight); mirror endpoint residual<=max(6,.2span); overlap gate. Scores not probabilities.',footDefinition='COCO wholebody: toe=mean(big_toe,small_toe), heel=heel. Not blade contact point.',url=Wholebody.MODE['performance']['pose'])
 items=[];start=time.time()
 for item in manifest['items']:
  if args.attempt and item['attemptId'] not in args.attempt:continue
  aid=item['attemptId'];pose_path=ROOT/f'data/pose-batch-v1/{aid}.json';pose=json.loads(pose_path.read_text());pose_sha=sha(pose_path)
  assert pose['sourceSha256']==item['sourceSha256'];points={f['frameIndex']:f['landmarks'] for f in pose['frames']}
  path=cache/f'{aid}.raw.json';existing=json.loads(path.read_text()) if path.exists() else {};raw=existing.get('frames',{}) if existing.get('weightsSha256')==weights_sha and existing.get('poseSha256')==pose_sha else {};frames=[]
  for f in item['frames']:
   n=f['frameIndex'];src=ROOT/'data/axel-demo-v1'/f['image'];digest=sha(src)
   if digest!=f['sourceFrameSha256']:raise ValueError('Source checksum mismatch')
   entry=raw.get(str(n))
   if not entry or entry['sourceFrameSha256']!=digest:
    im=cv2.imread(str(src));assert im.shape[:2]==(720,1280)
    lm=[p for p in points[n] if p['confidence']>.5 and 0<=p['x']<=1 and 0<=p['y']<=1]
    if len(lm)<6:entry=dict(sourceFrameSha256=digest,missing=True)
    else:
     xs=[p['x']*1280 for p in lm];ys=[p['y']*720 for p in lm];box=[max(0,min(xs)-40),max(0,min(ys)-40),min(1280,max(xs)+40),min(720,max(ys)+40)]
     kp,sc=model(im,bboxes=[box]);flipbox=[1279-box[2],box[1],1279-box[0],box[3]];fk,fs=model(cv2.flip(im,1),bboxes=[flipbox])
     entry=dict(sourceFrameSha256=digest,box=box,bodyHeight=box[3]-box[1],points=kp[0,:23].tolist(),scores=sc[0,:23].tolist(),mirrored=fk[0,:23].tolist(),mirrorScores=fs[0,:23].tolist())
    raw[str(n)]=entry
   pred=[] if entry.get('missing') else candidates(entry['points'],entry['scores'],entry['mirrored'],entry['mirrorScores'],1280,720,entry['bodyHeight'])
   frames.append(dict(frameIndex=n,image=f['image'],sourceFrameSha256=digest,candidates=pred))
  path.write_text(json.dumps(dict(weightsSha256=weights_sha,poseSha256=pose_sha,frames=raw),allow_nan=False))
  frames=landing_candidates(temporal_checks(frames),item['firstContact'])
  items.append({**{k:item[k] for k in ('attemptId','athlete','sourceSha256','firstContact','lastContact')},'frames':frames})
  print(aid,len(frames),'visible',sum(c['status']=='visible' for f in frames for c in f['candidates']),f'{time.time()-start:.1f}s',flush=True)
 result=dict(schemaVersion=1,model=settings['model'],width=1280,height=720,fps=50,settings=settings,items=items)
 # Atomic manifest replacement; assets are independent of this inference task.
 destination=ROOT/'data/axel-demo-v1/boot-workbench-data.json';tmp=destination.with_suffix('.tmp');tmp.write_text(json.dumps(result,ensure_ascii=False,allow_nan=False));tmp.replace(destination)
 (cache/'settings.json').write_text(json.dumps(settings,indent=2))
 print('Complete',len(items),'attempts',sum(len(i['frames']) for i in items),'frames',flush=True)
if __name__=='__main__':main()
