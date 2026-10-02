"""Binary expert rotation experiment with nested athlete-grouped feature selection.

Fixed candidates before observing results: skate, flow, pose, their concatenation.
Nearest class centroid throughout; inner balanced accuracy selects feature family.
"""
import hashlib,json
from pathlib import Path
import numpy as np
from run_rotation_proxy_baseline import athlete_folds,fit_preprocessor,transform,metrics,evaluate
from element_sign import features as skate_features
from element_sign_pose import pose_features
from image_motion import pool_motion


def predict(x,y,train,test):
 state=fit_preprocessor(x[train]);a=transform(x[train],state);b=transform(x[test],state)
 present=np.unique(y[train]);centroids=np.array([a[y[train]==c].mean(0) for c in present])
 return present[((b[:,None,:]-centroids[None,:,:])**2).sum(2).argmin(1)]


def nested_evaluate(families,y,groups):
 groups=np.asarray(groups);predictions=np.zeros(len(y),dtype=int);folds=[]
 for train,test in athlete_folds(groups):
  scores={};inner_folds=[]
  for inner_train,inner_test in athlete_folds(groups[train]):
   inner_folds.append(dict(trainIndices=train[inner_train].tolist(),testIndices=train[inner_test].tolist()))
  for name,x in families.items():
   p=np.zeros(len(y),dtype=int)
   for inner in inner_folds:p[inner['testIndices']]=predict(x,y,inner['trainIndices'],inner['testIndices'])
   scores[name]=metrics(y[train],p[train])['balancedAccuracy']
  # Dict insertion order is the fixed, predeclared tie breaker.
  selected=max(families,key=lambda name:scores[name] if scores[name] is not None else -1)
  predictions[test]=predict(families[selected],y,train,test)
  folds.append(dict(heldOutAthlete=str(groups[test[0]]),trainIndices=train.tolist(),testIndices=test.tolist(),innerFolds=inner_folds,innerBalancedAccuracy=scores,selected=selected))
 return dict(predictions=predictions.tolist(),metrics=metrics(y,predictions),folds=folds,
  majority=evaluate(next(iter(families.values())),y,groups,majority=True),
  fixedCandidates={name:evaluate(x,y,groups) for name,x in families.items()})


def run(root):
 hashes={}
 def read(path):
  raw=(root/path).read_bytes();hashes[str(path)]=hashlib.sha256(raw).hexdigest();return json.loads(raw)
 labels=read(Path('data/rotation-expert-v1/resolved/revision-2/assessments.json'))
 manifest=read(Path('data/axel-demo-v1/boot-workbench-data.json'));byid={r['attemptId']:r for r in manifest['items']}
 flow_cache=read(Path('work/step30-image-motion/results.json'))
 # Verify original cached image-flow provenance, not only the derived flow files.
 for path,digest in flow_cache['inputSha256'].items():
  actual=hashlib.sha256((root/path).read_bytes()).hexdigest()
  if actual!=digest:raise ValueError('Flow cache source changed: '+path)
  hashes[path]=actual
 flow_reference={r['attemptId']:v for r,v in zip(flow_cache['records'],flow_cache['features'])}
 records=[];excluded=[];families={name:[] for name in ('skate','flow','pose','combined')}
 for label in labels['assessments']:
  aid=label['attemptId'];assessment=label['rotationAssessment'];item=byid.get(aid)
  if assessment not in ('apparently_complete','apparently_short'):
   excluded.append(dict(attemptId=aid,reason='Unknown expert binary assessment'));continue
  if item is None:raise ValueError('Missing boot manifest '+aid)
  for key in ('sourceSha256','lastContact','firstContact'):
   if item[key]!=label[key]:raise ValueError('Provenance mismatch '+aid+' '+key)
  pose=read(Path('data/pose-batch-v1')/(aid+'.json'))
  if pose['sourceSha256']!=label['sourceSha256'] or pose['videoId']!=label['videoId']:raise ValueError('Pose provenance '+aid)
  rows=read(Path('work/step30-image-motion')/(aid+'.flow.json'))
  values=dict(skate=skate_features(item),flow=pool_motion(rows,item['lastContact'],item['firstContact']),pose=pose_features(pose,item))
  if not np.allclose(values['flow'],np.asarray(flow_reference[aid],dtype=float),equal_nan=True):raise ValueError('Flow rows differ from original feature cache '+aid)
  values['combined']=np.concatenate([values[name] for name in ('skate','flow','pose')])
  for name in families:families[name].append(values[name])
  records.append(dict(attemptId=aid,athlete=item['athlete'],videoId=label['videoId'],sourceSha256=label['sourceSha256'],lastContact=item['lastContact'],firstContact=item['firstContact'],truth=int(assessment=='apparently_short')))
 families={name:np.asarray(x,dtype=float) for name,x in families.items()};y=np.array([r['truth'] for r in records]);groups=np.array([r['athlete'] for r in records])
 for train,test in athlete_folds(groups):
  for key in ('videoId','sourceSha256'):assert {records[i][key] for i in train}.isdisjoint({records[i][key] for i in test})
 result=nested_evaluate(families,y,groups)
 result.update(schemaVersion=1,records=records,excluded=excluded,inputSha256=hashes,
  features={name:[[float(v) if np.isfinite(v) else None for v in row] for row in x] for name,x in families.items()},
  classes={'0':'expert apparently complete','1':'expert apparently short (including q)'},
  method='Nested leave-one-athlete-out; fixed skate, flow, pose, combined candidates; inner balanced accuracy selection, declared order ties; nearest class centroid; imputation and scaling fitted only on each training fold; no tuning against outer results.',
  limitations=['Known Axel clips and manual contact boundaries, not automatic Axel recognition','Single previously inspected event; development validation only','Five complete vs fifteen short; majority accuracy 75% alone is uninformative','Binary clean refers to rotation assessment, not overall landing quality','No true rotation degrees or revolution count measured; q included as expert short'])
 return result

if __name__=='__main__':
 root=Path(__file__).resolve().parents[1];result=run(root);out=root/'work/binary_rotation';out.mkdir(exist_ok=True)
 (out/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
 print(json.dumps(dict(nested=result['metrics'],majority=result['majority']['metrics'],fixed={k:v['metrics'] for k,v in result['fixedCandidates'].items()}),indent=2))
