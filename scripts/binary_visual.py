"""Frozen ImageNet ResNet18 lower-body features; fixed grouped binary experiment."""
import hashlib,json
from pathlib import Path
import numpy as np
from run_rotation_proxy_baseline import athlete_folds,fit_preprocessor,transform,metrics,evaluate
OFFSETS=(-8,-4,-1,0,4)
WEIGHTS=Path('/path/to/workspace/work/phase-cache/torch/checkpoints/resnet18-f37072fd.pth')

def lower_box(points,width,height):
 names={f'{side}_{part}' for side in ('left','right') for part in ('hip','knee','ankle')}
 p={r['name']:np.array([r['x']*width,r['y']*height]) for r in points if r['name'] in names and r.get('confidence',0)>=.5 and np.isfinite([r['x'],r['y']]).all() and 0<=r['x']<=1 and 0<=r['y']<=1}
 if len(p)<4 or not any(n.endswith('hip') for n in p) or not any(n.endswith('ankle') for n in p):return None
 a=np.array(list(p.values()));lo=a.min(0);hi=a.max(0);span=hi-lo
 if span[1]<10:return None
 # Fixed padding, including boot below ankle; no shoulders/head or side identities.
 pad=np.array([max(span[0]*.2,span[1]*.1),span[1]*.15])
 lo=np.maximum(lo-pad,0);hi=np.minimum(hi+pad,[width,height])
 return [int(lo[0]),int(lo[1]),int(np.ceil(hi[0])),int(np.ceil(hi[1]))]

def pool(vectors):
 return np.concatenate([vectors.mean(0),vectors[-1]-vectors[0]])

def evaluate_visual(x,y,groups):
 groups=np.asarray(groups);pred=np.zeros(len(y),dtype=int);scores=np.zeros(len(y));folds=[]
 for train,test in athlete_folds(groups):
  # Mean imputation/standardization strictly inside each outer fold.
  state=fit_preprocessor(x[train]);a=transform(x[train],state);b=transform(x[test],state)
  counts=np.bincount(y[train],minlength=2)
  if np.any(counts==0):scores[test]=float(np.argmax(counts))
  else:
   weights=len(train)/(2*counts[y[train]])
   center=np.average(a,axis=0,weights=weights);target=np.average(y[train],weights=weights)
   a=(a-center)*np.sqrt(weights[:,None]);z=(y[train]-target)*np.sqrt(weights)
   alpha=np.linalg.solve(a@a.T+10*np.eye(len(train)),z)
   scores[test]=(b-center)@a.T@alpha+target
  pred[test]=(scores[test]>=.5).astype(int)
  folds.append(dict(heldOutAthlete=str(groups[test[0]]),trainIndices=train.tolist(),testIndices=test.tolist(),trainingClassCounts=counts.tolist()))
 return dict(predictions=pred.tolist(),scores=scores.tolist(),metrics=metrics(y,pred),folds=folds,majority=evaluate(x,y,groups,majority=True))

def run(root):
 import torch
 from torchvision.models import resnet18,ResNet18_Weights
 from PIL import Image
 torch.set_num_threads(2)
 hashes={}
 def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
 def read(path):
  hashes[str(path.relative_to(root))]=digest(path);return json.loads(path.read_text())
 weights_sha=digest(WEIGHTS)
 # weights=None prevents implicit downloads. Local checkpoint only, CPU serial inference.
 model=resnet18(weights=None);model.load_state_dict(torch.load(WEIGHTS,map_location='cpu',weights_only=True));model.fc=torch.nn.Identity();model.eval()
 preprocess=ResNet18_Weights.IMAGENET1K_V1.transforms()
 labels=read(root/'data/rotation-expert-v1/resolved/revision-2/assessments.json')['assessments']
 manifest=read(root/'data/axel-demo-v1/boot-workbench-data.json');items={r['attemptId']:r for r in manifest['items']}
 out=root/'work/binary_visual';out.mkdir(exist_ok=True);cachepath=out/'embeddings.json';cache=json.loads(cachepath.read_text()) if cachepath.exists() else {};records=[];features=[];excluded=[]
 for label in labels:
  aid=label['attemptId']
  if label['rotationAssessment'] not in ('apparently_complete','apparently_short'):
   excluded.append(dict(attemptId=aid,reason='Unknown expert binary assessment'));continue
  item=items[aid]
  for key in ('sourceSha256','firstContact','lastContact'):
   if item[key]!=label[key]:raise ValueError('Manifest provenance '+aid)
  posepath=root/f'data/pose-batch-v1/{aid}.json';pose=read(posepath)
  if pose['sourceSha256']!=label['sourceSha256'] or pose['videoId']!=label['videoId']:raise ValueError('Pose provenance '+aid)
  frames={r['frameIndex']:r for r in item['frames']};points={r['frameIndex']:r['landmarks'] for r in pose['frames']};vectors=[];details=[]
  for offset in OFFSETS:
   index=item['firstContact']+offset;f=frames[index];path=root/'data/axel-demo-v1'/f['image'];sha=digest(path)
   if sha!=f['sourceFrameSha256']:raise ValueError('Image provenance '+aid)
   hashes[str(path.relative_to(root))]=sha
   with Image.open(path) as source:
    image=source.convert('RGB');box=lower_box(points[index],*image.size)
    details.append(dict(frameIndex=index,image=f['image'],sourceFrameSha256=sha,crop=box))
    if box is None:continue
    key=hashlib.sha256(json.dumps([sha,box,weights_sha,'RGB-v1-ImageNet-transform-512'],sort_keys=True).encode()).hexdigest()
    if key not in cache:
     with torch.inference_mode():vector=model(preprocess(image.crop(box)).unsqueeze(0)).numpy()[0]
     cache[key]=vector.tolist()
    vectors.append(np.asarray(cache[key],dtype=float))
  if len(vectors)!=len(OFFSETS):
   excluded.append(dict(attemptId=aid,reason='Missing confident lower-body crop in fixed five-frame sequence',frames=details));continue
  features.append(pool(np.array(vectors)));records.append(dict(attemptId=aid,athlete=item['athlete'],videoId=label['videoId'],sourceSha256=label['sourceSha256'],truth=int(label['rotationAssessment']=='apparently_short'),frames=details))
  print(aid,flush=True)
 cachepath.write_text(json.dumps(cache,allow_nan=False))
 x=np.array(features);y=np.array([r['truth'] for r in records]);groups=np.array([r['athlete'] for r in records])
 for train,test in athlete_folds(groups):
  for key in ('videoId','sourceSha256'):assert {records[i][key] for i in train}.isdisjoint({records[i][key] for i in test})
 result=evaluate_visual(x,y,groups)
 result.update(schemaVersion=1,records=records,excluded=excluded,features=x.tolist(),inputSha256=hashes,weightsSha256=weights_sha,embeddingCacheSha256=digest(cachepath),
  method='Frozen local ImageNet ResNet18 avgpool512; confidence>=0.5 hips/knees/ankles crop with fixed padding; RGB official V1 transforms; offsets[-8,-4,-1,0,4]; feature mean512+last-minus-first512; fixed class-balanced ridge alpha10 with train-only imputation/standardization and intercept; no tuning; CPU eval inference.',
  scope='Single previously viewed event; known Axel/manual landing; not automatic detection or measured degrees. Binary short includes q. No outer labels used in preprocessing or selection; no feature/model selection performed.')
 (out/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False));return result

if __name__=='__main__':
 result=run(Path(__file__).resolve().parents[1]);print(json.dumps(dict(metrics=result['metrics'],majority=result['majority']['metrics'],excluded=result['excluded']),ensure_ascii=False,indent=2))
