"""Fixed camera-roll invariant image-plane skate motion, not underrotation degrees."""
import hashlib,json
from pathlib import Path
import numpy as np
from run_rotation_proxy_baseline import evaluate,athlete_folds
from binary_visual import evaluate_visual
FEATURES=['visible_frame_fraction','adjacent_interval_fraction','mean_absolute_turn_radians','mean_signed_turn_radians','absolute_sum_signed_turn_radians','early_mean_absolute_turn_radians','late_mean_absolute_turn_radians','mean_toe_motion_in_foot_lengths','mean_heel_motion_in_foot_lengths']

def pivot_features(item):
 points={}
 for frame in item['frames']:
  offset=frame['frameIndex']-item['firstContact']
  if not 0<=offset<=10:continue
  c=next((c for c in frame['candidates'] if c['side']=='landing' and c['status']=='visible'),None)
  if c is None or c.get('heel') is None or c.get('toe') is None:continue
  heel,toe=np.array(c['heel'],dtype=float),np.array(c['toe'],dtype=float);v=toe-heel;length=np.linalg.norm(v)
  if not np.isfinite([*heel,*toe,length]).all() or length<=0:continue
  points[offset]=(heel,toe,v/length,length)
 rows=[]
 for index in range(1,11):
  if index not in points or index-1 not in points:continue
  h0,t0,u0,l0=points[index-1];h1,t1,u1,l1=points[index]
  angle=np.arctan2(u0[0]*u1[1]-u0[1]*u1[0],np.dot(u0,u1))
  rows.append((index,angle,np.linalg.norm(t1-t0)/((l0+l1)/2),np.linalg.norm(h1-h0)/((l0+l1)/2)))
 result=[len(points)/11,len(rows)/10]
 if not rows:return np.array(result+[np.nan]*7)
 angles=np.array([r[1] for r in rows]);result.extend([np.mean(np.abs(angles)),angles.mean(),abs(angles.sum())])
 for lo,hi in ((1,4),(5,10)):
  values=[abs(r[1]) for r in rows if lo<=r[0]<=hi];result.append(np.mean(values) if values else np.nan)
 result.extend([np.mean([r[j] for r in rows]) for j in (2,3)])
 return np.array(result)

def run(root):
 hashes={}
 def read(path):
  raw=(root/path).read_bytes();hashes[path]=hashlib.sha256(raw).hexdigest();return json.loads(raw)
 labels=read('data/rotation-expert-v1/resolved/revision-2/assessments.json')['assessments'];manifest=read('data/axel-demo-v1/boot-workbench-data.json');items={r['attemptId']:r for r in manifest['items']};records=[];excluded=[];vectors=[]
 for label in labels:
  aid=label['attemptId']
  if label['rotationAssessment'] not in ('apparently_complete','apparently_short'):
   excluded.append(dict(attemptId=aid,reason='Unknown expert assessment'));continue
  item=items[aid]
  for key in ('sourceSha256','lastContact','firstContact'):
   if item[key]!=label[key]:raise ValueError('Source/contact mismatch '+aid)
  vector=pivot_features(item);vectors.append(vector);records.append(dict(attemptId=aid,athlete=item['athlete'],videoId=label['videoId'],sourceSha256=label['sourceSha256'],truth=int(label['rotationAssessment']=='apparently_short'),visibleFrames=round(vector[0]*11),adjacentIntervals=round(vector[1]*10)))
 x=np.array(vectors);y=np.array([r['truth'] for r in records]);groups=np.array([r['athlete'] for r in records])
 for train,test in athlete_folds(groups):
  for key in ('videoId','sourceSha256'):assert {records[i][key] for i in train}.isdisjoint({records[i][key] for i in test})
 result=dict(schemaVersion=1,records=records,excluded=excluded,inputSha256=hashes,featureNames=FEATURES,features=[[float(v) if np.isfinite(v) else None for v in row] for row in x],variants={'ridge':evaluate_visual(x,y,groups),'centroid':evaluate(x,y,groups),'majority':evaluate(x,y,groups,majority=True)},
  method='Predeclared nine image-plane pivot proxies in firstContact..+10; visible landing candidates only, strictly adjacent source frames; shortest circular direction changes; fixed ridge alpha10 class balanced versus nearest class centroid; train-only preprocessing; grouped by athlete; no search.',
  limitations=['Known Axel and manually labeled first contact; not automatic identification or physical degree measurement','Camera roll, fixed translation and scale invariance, not perspective or time-varying camera-motion invariance','Landing side is existing heuristic; identity/heel-toe errors and foreshortening can produce spurious pivot','No bridging gaps; absolute sum of signed changes describes observed intervals only, not full net turn across missing frames','One previously inspected event, five clean vs fifteen short; no independent test; no winner selected after outer results'])
 out=root/'work/binary_pivot';out.mkdir(exist_ok=True);(out/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False));return result
if __name__=='__main__':
 result=run(Path(__file__).resolve().parents[1]);print(json.dumps({k:v['metrics'] for k,v in result['variants'].items()},indent=2))
