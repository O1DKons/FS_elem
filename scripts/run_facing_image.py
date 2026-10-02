"""Fixed grayscale HOG orientation baseline, grouped by athlete."""
import json,hashlib,html,argparse
from pathlib import Path
import cv2,numpy as np
from run_rotation_proxy_baseline import athlete_folds
ROOT=Path(__file__).resolve().parents[1]
IMPORT='data/facing-expert-v1/imports/66ca3bc604d30150240058357546ec0e80e1239c5d7ad579b9b6286f6c28a785/labels.json'
CLASSES=['front','back','side']
def descriptor(image,points):
 names=['left_shoulder','right_shoulder','left_hip','right_hip']
 p={r['name']:np.array([r['x']*image.shape[1],r['y']*image.shape[0]]) for r in points if r.get('confidence',0)>=.5 and np.isfinite([r['x'],r['y']]).all() and 0<=r['x']<=1 and 0<=r['y']<=1}
 if not all(n in p for n in names):return None,None
 shoulder=(p[names[0]]+p[names[1]])/2;hip=(p[names[2]]+p[names[3]])/2
 size=np.linalg.norm(shoulder-hip)
 if size<10:return None,None
 center=(shoulder+hip)/2
 x0=max(0,int(center[0]-size*.85));x1=min(image.shape[1],int(center[0]+size*.85))
 y0=max(0,int(min(shoulder[1],hip[1])-size*.8));y1=min(image.shape[0],int(max(shoulder[1],hip[1])+size*.2))
 if x1-x0<10 or y1-y0<10:return None,None
 crop=cv2.resize(image[y0:y1,x0:x1],(64,128))
 hog=cv2.HOGDescriptor((64,128),(16,16),(8,8),(8,8),9).compute(crop).ravel()
 return hog/max(np.linalg.norm(hog),1e-12),[x0,y0,x1,y1]
def main():
 parser=argparse.ArgumentParser()
 parser.add_argument('--expanded',action='store_true')
 args=parser.parse_args()
 source=IMPORT
 manifest_path='data/axel-demo-v1/facing-review-data.json'
 if args.expanded:
  source='data/facing-expert-v1/imports/093268b580c65caf8a21c44c85a310bffc401b17eaab43d7841454c46a035ed4/labels.json'
  manifest_path='data/axel-demo-v1/facing-review-expanded-data.json'
 paths=[source,manifest_path];hashes={}
 def read(path):
  raw=(ROOT/path).read_bytes();hashes[path]=hashlib.sha256(raw).hexdigest();return json.loads(raw)
 labels=read(paths[0])['labels'];manifest=read(paths[1])['frames']
 lookup={(r['attemptId'],r['frameIndex']):r for r in manifest}
 records=[];vectors=[];excluded=[]
 for label in labels:
  r=lookup[(label['attemptId'],label['frameIndex'])]
  if any(label[k]!=r[k] for k in ['sourceSha256','sourceFrameSha256']):raise ValueError('Frame provenance mismatch')
  path='data/pose-batch-v1/'+r['attemptId']+'.json';pose=read(path)
  if pose['sourceSha256']!=r['sourceSha256']:raise ValueError('Pose source mismatch')
  frame=next(f for f in pose['frames'] if f['frameIndex']==r['frameIndex'])
  imagepath='data/axel-demo-v1/'+r['image'];digest=hashlib.sha256((ROOT/imagepath).read_bytes()).hexdigest()
  if digest!=r['sourceFrameSha256']:raise ValueError('Image changed')
  hashes[imagepath]=digest
  x,box=descriptor(cv2.imread(str(ROOT/imagepath),cv2.IMREAD_GRAYSCALE),frame['landmarks'])
  if x is None or label['facing'] not in CLASSES:excluded.append(label);continue
  vectors.append(x);records.append(dict(**r,truth=label['facing'],crop=box))
 x=np.array(vectors);y=np.array([r['truth'] for r in records]);groups=[r['athlete'] for r in records]
 predictions=['']*len(y);majority=['']*len(y);folds=[]
 for train,test in athlete_folds(groups):
  present=sorted(set(y[train]));centers=np.array([x[train][y[train]==c].mean(0) for c in present])
  guesses=((x[test,None,:]-centers[None,:,:])**2).sum(2).argmin(1)
  common=max(present,key=lambda c:int(sum(y[train]==c)))
  for i,g in zip(test,guesses):predictions[i]=present[g];majority[i]=common
  folds.append(dict(athlete=groups[test[0]],trainIndices=train.tolist(),testIndices=test.tolist()))
 def score(pred):
  recall={c:sum(a==c and b==c for a,b in zip(y,pred))/sum(y==c) if sum(y==c) else None for c in CLASSES}
  return dict(correct=sum(a==b for a,b in zip(y,pred)),total=len(y),recall=recall,macroRecall=float(np.mean([v for v in recall.values() if v is not None])))
 result=dict(records=records,predictions=predictions,metrics=score(predictions),majority=score(majority),folds=folds,excluded=excluded,inputSha256=hashes,method='Fixed grayscale HOG64x128 L2 normalized, Euclidean nearest class centroid. Pose used for torso/head crop only. No tuning. Previously viewed single-event development data; no independent test. No underrotation inference.')
 out=ROOT/('work/step41-facing-expanded' if args.expanded else 'work/step40-facing-image');out.mkdir(parents=True,exist_ok=True)
 (out/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
 names={'front':'Лицом','back':'Спиной','side':'Боком'}
 rows=[]
 for r,p in zip(records,predictions):
  rows.append('<tr><td>'+html.escape(r['athlete'])+'</td><td>'+str(r['frameIndex'])+'</td><td>'+names[r['truth']]+'</td><td>'+names[p]+'</td></tr>')
 page='<meta charset="utf-8"><title>Ориентация по изображению</title><style>body{font:18px system-ui;background:#101923;color:#eef;margin:40px}td,th{padding:12px;border-bottom:1px solid #456}</style><h1>Ориентация корпуса по изображению</h1><p>Предварительная проверка: все кадры проверяемой спортсменки исключены из обучения. Набор разработки, не независимый тест.</p><p>Совпадений: '+str(result['metrics']['correct'])+'/'+str(len(y))+'. Базовый ответ большинства: '+str(result['majority']['correct'])+'/'+str(len(y))+'.</p><p>Это ориентация относительно камеры, не знак недокрута.</p><table><tr><th>Спортсменка</th><th>Кадр</th><th>Эксперт</th><th>Модель</th></tr>'+''.join(rows)+'</table>'
 (ROOT/('data/axel-demo-v1/facing-image-expanded-results.html' if args.expanded else 'data/axel-demo-v1/facing-image-results.html')).write_text(page)
 print(json.dumps({k:result[k] for k in ['metrics','majority','excluded']},indent=2))
if __name__=='__main__':main()
