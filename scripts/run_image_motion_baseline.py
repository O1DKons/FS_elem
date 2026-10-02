"""One fixed image-motion experiment on resolved expert labels, grouped by athlete."""
import json,hashlib,time
from pathlib import Path
import numpy as np,cv2
from image_motion import body_box,describe_flow,pool_motion
from run_rotation_proxy_baseline import evaluate,athlete_folds
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'work/step30-image-motion'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 OUT.mkdir(exist_ok=True);start=time.perf_counter()
 review=ROOT/'work/step29-expert-revision/results.json';base=json.loads(review.read_text());records=base['records']
 manifest=json.loads((ROOT/'data/axel-demo-v1/rotation-review-data.json').read_text());items={i['attemptId']:i for i in manifest['items']};features=[];quality=[];hashes={str(review.relative_to(ROOT)):sha(review)}
 for record in records:
  aid=record['attemptId'];item=items[aid];posepath=ROOT/f'data/pose-batch-v1/{aid}.json';pose=json.loads(posepath.read_text());hashes[str(posepath.relative_to(ROOT))]=sha(posepath)
  assert pose['sourceSha256']==item['sourceSha256'] and pose['videoId']==item['videoId']
  points={f['frameIndex']:f['landmarks'] for f in pose['frames']};rows=[];previous=None;prevtime=None;previndex=None
  # Exactly the frames needed for flight and fixed200ms landing context.
  selected=[f for f in item['frames'] if item['lastContact']<=f['frameIndex']<=item['firstContact']+10]
  assert selected[0]['frameIndex']==item['lastContact'] and selected[-1]['frameIndex']==item['firstContact']+10
  for f in selected:
   path=ROOT/'data/axel-demo-v1'/f['image'];digest=sha(path);assert digest==f['sourceFrameSha256'];hashes[str(path.relative_to(ROOT))]=digest
   gray=cv2.imread(str(path),cv2.IMREAD_GRAYSCALE)
   if gray is None or gray.shape!=(720,1280):raise ValueError('Invalid source image')
   gray=cv2.resize(gray,(320,180),interpolation=cv2.INTER_AREA)
   if previous is not None:
    assert f['frameIndex']==previndex+1
    flow=cv2.calcOpticalFlowFarneback(previous,gray,None,.5,3,15,3,5,1.2,0)
    # Field is located in previous-image coordinates; ROI must use that same frame.
    box=body_box(points[previndex]);v=describe_flow(flow,box,f['time']-prevtime)
    rows.append(dict(frameIndex=f['frameIndex'],values=[float(x) if np.isfinite(x) else None for x in v]))
   previous=gray;prevtime=f['time'];previndex=f['frameIndex']
  pooled=pool_motion(rows,item['lastContact'],item['firstContact']);features.append(pooled)
  quality.append(dict(attemptId=aid,pairs=len(rows),validPairs=sum(all(v is not None for v in r['values']) for r in rows)))
  (OUT/f'{aid}.flow.json').write_text(json.dumps(rows,allow_nan=False));print(aid,len(rows),flush=True)
 x=np.array(features);y=np.array([r['target'] for r in records]);groups=[r['athlete'] for r in records]
 for train,test in athlete_folds(groups):assert {records[i]['videoId'] for i in train}.isdisjoint({records[i]['videoId'] for i in test})
 variants={'training_majority':evaluate(x,y,groups,majority=True),'image_motion_only':evaluate(x,y,groups)}
 for variant in variants.values():
  m=variant['metrics'];m['recallApparentlyComplete']=m.pop('recallUnmarked');m['recallApparentlyShort']=m.pop('recallMarked')
 result=dict(schemaVersion=1,classes=base['classes'],inputSha256=hashes,opencvVersion=cv2.__version__,method='Farneback320x180; fixed parameters(.5,3,15,3,5,1.2,0); previous-frame pose ROI confidence>=.5 margin10%; residual relative to ROI median translation; body-height/sec normalization; mean/std3 descriptors across flight and first200ms after manual landing; nearest class centroid with training-only scaling, no tuning.',featureNames=[f'{phase}_{measure}_{stat}' for phase in ('flight','landing200ms') for measure in ('absHorizontal','absVertical','speedP75') for stat in ('mean','std')],records=[{k:r[k] for k in ('attemptId','athlete','videoId','assessment','target')} for r in records],features=[[float(v) if np.isfinite(v) else None for v in row] for row in x],quality=quality,variants=variants,elapsedSeconds=time.perf_counter()-start,limitations=['Known Axel windows and manual contact boundaries; not full-program detection','ROI still uses pose positions; sides are not used but crop errors remain','Optical flow can include ice/background and camera perspective; not rotation angle','20 previously inspected attempts,15 athletes,one event; no independent external test','Repeated experiments make this a development set; further new untouched evaluation is required'])
 (OUT/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False));print(json.dumps({k:v['metrics'] for k,v in variants.items()},indent=2),flush=True)
if __name__=='__main__':main()
