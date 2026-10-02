"""Fixed nested athlete exclusion for predicted orientation -> element sign."""
import json,hashlib,html
from pathlib import Path
import numpy as np,cv2
from run_facing_image import descriptor
from facing_crossfit import predict_facing
from run_rotation_proxy_baseline import athlete_folds,fit_preprocessor,transform
ROOT=Path(__file__).resolve().parents[1]
def main():
 hashes={}
 def read(path):
  raw=(ROOT/path).read_bytes();hashes[path]=hashlib.sha256(raw).hexdigest();return json.loads(raw)
 facing=read('work/step41-facing-expanded/results.json')
 base=read('work/step35-element-sign/results.json')
 for source in [facing,base]:
  for p,h in source['inputSha256'].items():
   if hashlib.sha256((ROOT/p).read_bytes()).hexdigest()!=h:raise ValueError('Stale input: '+p)
   hashes[p]=h
 manifest=read('data/axel-demo-v1/facing-review-expanded-data.json')['frames']
 vectors={};poses={}
 for r in manifest:
  aid=r['attemptId']
  if aid not in poses:poses[aid]=read('data/pose-batch-v1/'+aid+'.json')
  if poses[aid]['sourceSha256']!=r['sourceSha256']:raise ValueError('Pose mismatch')
  points=next(f['landmarks'] for f in poses[aid]['frames'] if f['frameIndex']==r['frameIndex'])
  path='data/axel-demo-v1/'+r['image'];raw=(ROOT/path).read_bytes();digest=hashlib.sha256(raw).hexdigest()
  if digest!=r['sourceFrameSha256']:raise ValueError('Image mismatch')
  hashes[path]=digest
  value,_=descriptor(cv2.imread(str(ROOT/path),cv2.IMREAD_GRAYSCALE),points)
  vectors[(aid,r['frameIndex'])]=value if value is not None else np.full(3780,np.nan)
 x=np.array([vectors[(r['attemptId'],r['frameIndex'])] for r in facing['records']])
 y=np.array([r['truth'] for r in facing['records']]);groups=np.array([r['athlete'] for r in facing['records']])
 records=base['records'];sg=np.array([r['athlete'] for r in records]);sy=np.array([r['truth'] for r in records])
 boots=np.array([[np.nan if v is None else v for v in r['features']] for r in records])
 queries=[]
 for r in records:
  frames=sorted([f for f in manifest if f['attemptId']==r['attemptId']],key=lambda f:f['frameIndex'])
  assert len(frames)==5
  queries.append(np.array([vectors[(f['attemptId'],f['frameIndex'])] for f in frames]))
 predictions={name:[None]*len(records) for name in ['orientation','combined']};folds=[]
 for train,test in athlete_folds(sg):
  held=sg[test[0]];features=[];audit=[]
  for i,r in enumerate(records):
   excluded={held,r['athlete']} if i in train else {held}
   p,used=predict_facing(x,y,groups,queries[i],excluded)
   assert not set(groups[used]) & excluded
   features.append(p.ravel())
   audit.append(dict(signIndex=i,excludedAthletes=sorted(excluded),facingTrainIndices=used))
  ff=np.array(features)
  for name,values in [('orientation',ff),('combined',np.column_stack([boots,ff]))]:
   state=fit_preprocessor(values[train]);a=transform(values[train],state);b=transform(values[test],state)
   present=sorted(set(sy[train]));centers=np.array([a[sy[train]==c].mean(0) for c in present])
   guesses=((b[:,None,:]-centers[None,:,:])**2).sum(2).argmin(1)
   for i,g in zip(test,guesses):predictions[name][i]=present[g]
  folds.append(dict(heldOutAthlete=held,trainIndices=train.tolist(),testIndices=test.tolist(),orientationTraining=audit))
 def score(p):
  recall={c:sum(a==c and b==c for a,b in zip(sy,p))/sum(sy==c) for c in sorted(set(sy))}
  return dict(correct=sum(a==b for a,b in zip(sy,p)),total=len(sy),macroRecall=float(np.mean(list(recall.values()))),recall=recall)
 result=dict(records=records,predictions=predictions,metrics={k:score(v) for k,v in predictions.items()},bootMetrics=base['metrics'],folds=folds,inputSha256=hashes,method='Fixed HOG nearest centroid facing, five one-hot predictions ordered -8,-4,-1,0,+4. Outer held-out athlete excluded from all orientation training. Sign training orientation additionally excludes its own athlete. No tuning. Previously inspected development set, not independent accuracy. Known 2A windows and manual contacts.')
 out=ROOT/'work/step42-facing-crossfit';out.mkdir(parents=True,exist_ok=True)
 (out/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
 rows=''.join('<tr><td>'+html.escape(r['athlete'])+'</td><td>'+html.escape(r['truth'])+'</td><td>'+html.escape(predictions['combined'][i])+'</td></tr>' for i,r in enumerate(records))
 page='<meta charset="utf-8"><title>Ориентация и знак</title><style>body{font:18px system-ui;background:#101923;color:#eef;margin:40px}td{padding:12px}</style><h1>Распознанная ориентация и знак прыжка</h1><p>Проверка на 19 известных акселях; это набор разработки. Спортсменка исключена из обучения обоих этапов. Ручная ориентация не подставляется в признаки.</p>'+''.join('<p>'+k+': '+str(v['correct'])+'/19</p>' for k,v in result['metrics'].items())+'<p>Прежний вариант по коньку: 12/19. Не автоматическое определение акселя и не измерение градусов.</p><table><tr><th>Спортсменка</th><th>Эксперт</th><th>Совместный вариант</th></tr>'+rows+'</table>'
 (ROOT/'data/axel-demo-v1/facing-sign-results.html').write_text(page)
 print(json.dumps(result['metrics'],indent=2))
if __name__=='__main__':main()
