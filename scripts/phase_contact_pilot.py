"""Fixed ordered pose contact proposal pilot, with explicit cropped-window baseline."""
import hashlib,json
from pathlib import Path
import numpy as np
from run_rotation_proxy_baseline import athlete_folds,fit_preprocessor,transform
PARTS=('shoulder','elbow','wrist','hip','knee','ankle','heel','foot_index')

def pose_features(pose):
 width,height=pose['coordinateSpace']['width'],pose['coordinateSpace']['height'];rows=[]
 for f in pose['frames']:
  p={r['name']:np.array([r['x']*width,r['y']*height]) for r in f['landmarks'] if r.get('confidence',0)>=.5 and np.isfinite([r['x'],r['y']]).all()}
  names=('left_hip','right_hip','left_shoulder','right_shoulder')
  if not all(n in p for n in names):rows.append(np.full(32,np.nan));continue
  hip=(p[names[0]]+p[names[1]])/2;shoulder=(p[names[2]]+p[names[3]])/2;length=np.linalg.norm(shoulder-hip)
  if length<1:rows.append(np.full(32,np.nan));continue
  row=[]
  for part in PARTS:
   pair=[p.get(side+'_'+part) for side in ('left','right')]
   # Ignore unreliable anatomical side IDs; sort pair by image x only.
   if any(v is None for v in pair):row.extend([np.nan]*4)
   else:
    for v in sorted(pair,key=lambda a:a[0]):row.extend((v-hip)/length)
  rows.append(row)
 geometry=np.asarray(rows)
 if len(rows)<3:raise ValueError('At least three frames required')
 # Offline local motion only; no timestamp, index, contact, sequence length features.
 motion=np.gradient(geometry,axis=0)
 return np.column_stack([geometry,motion])

def decode(probabilities):
 p=np.asarray(probabilities,dtype=float)
 if len(p)<3 or p.shape[1]!=3:raise ValueError('Three ordered states require >=3 frames')
 logp=np.log(np.clip(p,1e-12,1));score=np.full_like(logp,-np.inf);previous=np.zeros_like(logp,dtype=int);score[0,0]=logp[0,0]
 for i in range(1,len(p)):
  for state in range(3):
   options=[state] if state==0 else [state,state-1]
   prev=max(options,key=lambda s:score[i-1,s]);score[i,state]=score[i-1,prev]+logp[i,state];previous[i,state]=prev
 states=np.zeros(len(p),dtype=int);states[-1]=2
 for i in range(len(p)-1,0,-1):states[i-1]=previous[i,states[i]]
 return int(np.flatnonzero(states==0)[-1]),int(np.flatnonzero(states==2)[0])

def metric(records,key):
 errors=np.array([r[key+'Error'] for r in records])
 return dict(maeFrames=float(np.abs(errors).mean()),within2Frames=int(sum(abs(errors)<=2)),total=len(errors),medianAbsoluteError=float(np.median(abs(errors))),maxAbsoluteError=int(max(abs(errors))))

def run(root,jitter=False):
 from sklearn.ensemble import ExtraTreesClassifier
 import sklearn,joblib
 hashes={}
 def read(relative):
  raw=(root/relative).read_bytes();hashes[relative]=hashlib.sha256(raw).hexdigest();return json.loads(raw)
 manifest=read('data/axel-boundaries-v1/manifest.json')['items'];records=[];xs=[];ys=[]
 for r in manifest:
  pose=read('data/pose-batch-v1/'+r['attemptId']+'.json')
  assert pose['sourceSha256']==r['sourceSha256'] and pose['videoId']==r['videoId']
  indices=np.array([f['frameIndex'] for f in pose['frames']]);assert np.all(np.diff(indices)==1)
  last=r['boundaries']['lastContact'];first=r['boundaries']['firstContact']
  assert last['status']==first['status']=='user_confirmed'
  assert indices[0]<last['frameIndex']<first['frameIndex']<indices[-1]
  if jitter:
   digest=hashlib.sha256(r['attemptId'].encode()).digest()
   before=min(digest[0]%21,max(0,last['frameIndex']-int(indices[0])+1-5))
   after=min(digest[1]%21,max(0,int(indices[-1])-first['frameIndex']+1-5))
   pose=dict(pose,frames=pose['frames'][before:len(indices)-after])
   indices=np.array([f['frameIndex'] for f in pose['frames']])
  xs.append(pose_features(pose));ys.append(np.where(indices<=last['frameIndex'],0,np.where(indices<first['frameIndex'],1,2)))
  records.append(dict(attemptId=r['attemptId'],athlete=r['athleteGroup'],videoId=r['videoId'],sourceSha256=r['sourceSha256'],startFrame=int(indices[0]),endFrame=int(indices[-1]),lastContact=last['frameIndex'],firstContact=first['frameIndex']))
 groups=np.array([r['athlete'] for r in records]);folds=[];baseline=[]
 def fit(indices):
  x=np.concatenate([xs[i] for i in indices]);y=np.concatenate([ys[i] for i in indices]);state=fit_preprocessor(x)
  model=ExtraTreesClassifier(n_estimators=200,min_samples_leaf=5,class_weight='balanced',random_state=20260922,n_jobs=2)
  model.fit(transform(x,state),y);return model,state
 for train,test in athlete_folds(groups):
  for key in ('videoId','sourceSha256'):assert {records[i][key] for i in train}.isdisjoint({records[i][key] for i in test})
  model,state=fit(train)
  medians={key:int(np.rint(np.median([records[i][key]-records[i]['startFrame'] for i in train]))) for key in ('lastContact','firstContact')}
  for i in test:
   a,b=decode(model.predict_proba(transform(xs[i],state)));r=records[i];r['predictedLastContact']=r['startFrame']+a;r['predictedFirstContact']=r['startFrame']+b
   r['lastContactError']=r['predictedLastContact']-r['lastContact'];r['firstContactError']=r['predictedFirstContact']-r['firstContact']
   baseline.append(dict(attemptId=r['attemptId'],lastContactError=medians['lastContact']+r['startFrame']-r['lastContact'],firstContactError=medians['firstContact']+r['startFrame']-r['firstContact']))
  folds.append(dict(heldOutAthlete=str(groups[test[0]]),trainIndices=train.tolist(),testIndices=test.tolist(),trainingMedianOffsets=medians))
 result=dict(schemaVersion=1,contextJitter=bool(jitter),jitterMethod='SHA256 attempt ID bytes0/1 modulo21 trim leading/trailing ground frames, retain at least5; never a model feature' if jitter else None,records=records,metrics={key:metric(records,key) for key in ('lastContact','firstContact')},timingBaseline={key:metric(baseline,key) for key in ('lastContact','firstContact')},baselineRecords=baseline,folds=folds,inputSha256=hashes,sklearnVersion=sklearn.__version__,
  method='Fixed ExtraTrees200,minleaf5,classbalanced,seed20260922; 32 hip-centered torso-normalized pose coordinates +32 local differences; three-state monotonic maximum log-probability decoder, forced groundedbefore/flight/groundedafter; LOAO; train-only mean imputation/scaling.',
  limitations=['Pose windows were already cropped using manual contacts: strong timing prior; not independent short-video localization','Known one-jump sequence; decoder forces one flight, unsupported for no-jump/multiple-jump/fullprogram','No frame index/time/windowlength/identity/protocol/contact supplied to feature extraction','Manual contacts label training frames only; missing/occluded 2D pose and perspective remain confounds','Previously inspected single event; not production validated; proposals require review'])
 out=root/('work/phase-contact-pilot-jitter' if jitter else 'work/phase-contact-pilot');out.mkdir(exist_ok=True);(out/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
 model,state=fit(range(len(records)))
 artifact=dict(schemaVersion=1,model=model,preprocessor=state,provenance=result,featureParts=PARTS,featureCodeSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),status='experimental_known_jump_contact_proposal_not_production')
 joblib.dump(artifact,out/'classifier.joblib');return result
if __name__=='__main__':
 import argparse
 parser=argparse.ArgumentParser();parser.add_argument('--jitter',action='store_true');args=parser.parse_args()
 r=run(Path(__file__).resolve().parents[1],args.jitter);print(json.dumps({k:r[k] for k in ('metrics','timingBaseline')},indent=2))
