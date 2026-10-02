"""Fixed train-fold duration limits for the existing RTMW visual contact classifier.

No modification to live phase modules or existing trained artifacts.
"""
import hashlib,json
from pathlib import Path
import numpy as np
from phase_contact_pilot import decode,metric
from run_rotation_proxy_baseline import fit_preprocessor,transform,athlete_folds
MARGIN_FRAMES=4

def duration_bounds(records,train):
 lengths=[records[i]['firstContact']-records[i]['lastContact']-1 for i in train]
 if not lengths or min(lengths)<1:raise ValueError('Training flight states must have positive length')
 return dict(minAirborneFrames=max(1,min(lengths)-MARGIN_FRAMES),maxAirborneFrames=max(lengths)+MARGIN_FRAMES,trainingMinAirborneFrames=min(lengths),trainingMaxAirborneFrames=max(lengths),fixedMarginFrames=MARGIN_FRAMES)

def decode_duration(probabilities,min_airborne,max_airborne):
 p=np.asarray(probabilities,dtype=float)
 if p.ndim!=2 or p.shape[1]!=3 or not np.isfinite(p).all() or np.any(p<0) or np.any(p>1):raise ValueError('Expected finite three-state probabilities')
 if type(min_airborne) is not int or type(max_airborne) is not int or min_airborne<1 or max_airborne<min_airborne:raise ValueError('Invalid flight duration bounds')
 if len(p)<min_airborne+2:raise ValueError('Sequence too short for before/flight/after with trained duration bounds')
 prefix=np.vstack([np.zeros(3),np.cumsum(np.log(np.clip(p,1e-12,1)),axis=0)])
 best=None;best_score=-np.inf
 # At least one ground frame on either side; earliest boundaries win exact ties.
 for last in range(len(p)-2):
  firsts=np.arange(last+min_airborne+1,min(len(p),last+max_airborne+2))
  if not len(firsts):continue
  scores=prefix[last+1,0]+prefix[firsts,1]-prefix[last+1,1]+prefix[-1,2]-prefix[firsts,2]
  j=int(scores.argmax())
  if scores[j]>best_score:best_score=float(scores[j]);best=(last,int(firsts[j]))
 if best is None:raise ValueError('No valid duration-constrained ordered path')
 return best

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def run(root):
 from sklearn.ensemble import ExtraTreesClassifier
 import sklearn
 source=root/'work/phase-contact-rtmw';base=json.loads((source/'results.json').read_text());hashes={'work/phase-contact-rtmw/results.json':sha(source/'results.json'),'work/phase-contact-rtmw/features.npz':sha(source/'features.npz')}
 for path,digest in base['inputSha256'].items():
  if sha(root/path)!=digest:raise ValueError('Stale phase input '+path)
  hashes[path]=digest
 require_keys=('attemptId','athlete','videoId','sourceSha256','startFrame','endFrame','lastContact','firstContact')
 records=[{k:r[k] for k in require_keys} for r in base['records']];xs=[];ys=[]
 with np.load(source/'features.npz',allow_pickle=False) as data:
  if set(data.files)!={r['attemptId'] for r in records}:raise ValueError('Feature record coverage mismatch')
  for r in records:
   x=data[r['attemptId']];indices=np.arange(r['startFrame'],r['endFrame']+1)
   if x.shape!=(len(indices),576):raise ValueError('Cached feature shape mismatch')
   xs.append(x);ys.append(np.where(indices<=r['lastContact'],0,np.where(indices<r['firstContact'],1,2)))
 groups=np.array([r['athlete'] for r in records]);folds=[];baseline_rows=[];probabilities={}
 for train,test in athlete_folds(groups):
  for key in ('videoId','sourceSha256'):assert {records[i][key] for i in train}.isdisjoint({records[i][key] for i in test})
  x=np.concatenate([xs[i] for i in train]);y=np.concatenate([ys[i] for i in train]);state=fit_preprocessor(x)
  model=ExtraTreesClassifier(n_estimators=200,min_samples_leaf=5,class_weight='balanced',random_state=20260922,n_jobs=2);model.fit(transform(x,state),y)
  bounds=duration_bounds(records,train)
  for i in test:
   p=model.predict_proba(transform(xs[i],state));probabilities[records[i]['attemptId']]=p
   old_a,old_b=decode(p);r=records[i];original=base['records'][i]
   if old_a+r['startFrame']!=original['predictedLastContact'] or old_b+r['startFrame']!=original['predictedFirstContact']:raise ValueError('Frozen baseline OOF prediction failed to reproduce')
   baseline_rows.append(dict(attemptId=r['attemptId'],lastContactError=original['lastContactError'],firstContactError=original['firstContactError']))
   a,b=decode_duration(p,bounds['minAirborneFrames'],bounds['maxAirborneFrames'])
   r.update(predictedLastContact=r['startFrame']+a,predictedFirstContact=r['startFrame']+b,lastContactError=r['startFrame']+a-r['lastContact'],firstContactError=r['startFrame']+b-r['firstContact'],predictedAirborneFrames=b-a-1,baselineAirborneFrames=old_b-old_a-1)
  folds.append(dict(heldOutAthlete=str(groups[test[0]]),trainIndices=train.tolist(),testIndices=test.tolist(),durationBounds=bounds))
 result=dict(schemaVersion=1,records=records,metrics={key:metric(records,key) for key in ('lastContact','firstContact')},baselineMetrics={key:metric(baseline_rows,key) for key in ('lastContact','firstContact')},folds=folds,inputSha256=hashes,sklearnVersion=sklearn.__version__,allTrainingDurationBounds=duration_bounds(records,range(len(records))),
  method='Reproduce fixed ExtraTrees200/minleaf5/classbalanced/seed20260922 LOAO from cached RTMW+ResNet576 features. Only decoder differs: airborne-state length within training-fold min/max±4frames, >=1groundframe each side. No held-out durations/boundaries enter decoding. No tuning.',
  limitations=['Known single-jump jittered windows derived from manual contacts; not arbitrary video or fullprogram accuracy','Duration prior estimated from23 jumps/18 athletes in one event; may exclude different jump heights/rotation types/FPS','Airborne state count is firstContact-lastContact-1 at50Hz; not exact physical flight time','Constraints prevent very short states but do not prove real airborne contact or reject no-jump clips','All-training bounds provided only as an experimental deployment prior, never used for OOF metrics'])
 out=root/'work/phase-duration-v1';out.mkdir(exist_ok=True);(out/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False));np.savez_compressed(out/'oof-probabilities.npz',**probabilities)
 return result
if __name__=='__main__':
 r=run(Path(__file__).resolve().parents[1]);print(json.dumps({k:r[k] for k in ('metrics','baselineMetrics','allTrainingDurationBounds')},indent=2))
