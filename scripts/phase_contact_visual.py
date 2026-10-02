"""Frozen lower-body visual + pose contact proposals, fixed jittered athlete folds."""
import hashlib,json,inspect
from pathlib import Path
import numpy as np
from phase_contact_pilot import pose_features,decode,metric
from binary_visual import lower_box,WEIGHTS
from run_rotation_proxy_baseline import athlete_folds,fit_preprocessor,transform

def normalize_cached_frame(cached):
 if cached.get('missing'):return []
 from infer_jump_landmarks import normalize_wholebody
 return normalize_wholebody(cached['points'],cached['scores'],1280,720)

def combine_features(pose,frame_indices,images):
 return np.column_stack([pose,np.array([images.get(int(i),np.full(512,np.nan)) for i in frame_indices])])

def jitter_slice(aid,indices,last,first):
 digest=hashlib.sha256(aid.encode()).digest()
 before=min(digest[0]%21,max(0,last-int(indices[0])+1-5))
 after=min(digest[1]%21,max(0,int(indices[-1])-first+1-5))
 return slice(before,len(indices)-after)

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def extract_all(root,items,poses,out,hashes):
 import torch,torchvision
 from torchvision.models import resnet18,ResNet18_Weights
 from PIL import Image
 torch.set_num_threads(2);device='mps' if torch.backends.mps.is_available() else 'cpu'
 weightsha=sha(WEIGHTS);model=resnet18(weights=None);model.load_state_dict(torch.load(WEIGHTS,map_location='cpu',weights_only=True));model.fc=torch.nn.Identity();model.eval().to(device)
 preprocess=ResNet18_Weights.IMAGENET1K_V1.transforms();cachepath=out/'embeddings.npz'
 if cachepath.exists():
  with np.load(cachepath,allow_pickle=False) as data:cache={k:data[k] for k in data.files}
 else:cache={}
 # Reuse only exact same frozen-weight/crop/preprocessing keys from prior fixed visual experiment.
 prior=root/'work/binary_visual/embeddings.json'
 if prior.exists():
  for k,v in json.loads(prior.read_text()).items():cache.setdefault(k,np.asarray(v,dtype=np.float32))
 all_vectors={};details=[];batch=[];keys=[];missing=0
 def flush():
  if not batch:return
  with torch.inference_mode():values=model(torch.stack(batch).to(device)).cpu().numpy()
  for key,value in zip(keys,values):cache[key]=value
  batch.clear();keys.clear()
 for aid,pose in poses.items():
  lookup={f['frameIndex']:f for f in items[aid]['frames']};mapping={}
  for frame in pose['frames']:
   index=frame['frameIndex'];f=lookup[index];path=root/'data/axel-demo-v1'/f['image'];digest=sha(path)
   if digest!=f['sourceFrameSha256']:raise ValueError('Image SHA mismatch '+aid)
   hashes[str(path.relative_to(root))]=digest
   with Image.open(path) as source:
    image=source.convert('RGB');box=lower_box(frame['landmarks'],*image.size)
    if box is None:missing+=1;mapping[index]=None;details.append(dict(attemptId=aid,frameIndex=index,crop=None));continue
    key=hashlib.sha256(json.dumps([digest,box,weightsha,'RGB-v1-ImageNet-transform-512'],sort_keys=True).encode()).hexdigest();mapping[index]=key
    details.append(dict(attemptId=aid,frameIndex=index,crop=box,cacheKey=key))
    if key not in cache:
     batch.append(preprocess(image.crop(box)));keys.append(key)
     if len(batch)==16:flush()
  all_vectors[aid]=mapping
  print(json.dumps({'extractedAttempt':aid,'cacheEmbeddings':len(cache),'missingCropFrames':missing}),flush=True)
 flush();np.savez_compressed(cachepath,**cache)
 vectors={aid:{index:cache[key] for index,key in values.items() if key is not None} for aid,values in all_vectors.items()}
 provenance=dict(model='ResNet18',weights='ImageNet1K_V1',weightsSha256=weightsha,torchVersion=torch.__version__,torchvisionVersion=torchvision.__version__,device=device,batchSize=16,cropCodeSha256=hashlib.sha256(inspect.getsource(lower_box).encode()).hexdigest(),transform=str(preprocess),output='avgpool512',cacheSha256=sha(cachepath),missingCropFrames=missing)
 return vectors,details,provenance

def run(root,rtmw=False):
 from sklearn.ensemble import ExtraTreesClassifier
 import sklearn,joblib
 out=root/('work/phase-contact-rtmw' if rtmw else 'work/phase-contact-visual');out.mkdir(exist_ok=True);hashes={}
 def read(path):
  raw=(root/path).read_bytes();hashes[path]=hashlib.sha256(raw).hexdigest();return json.loads(raw)
 boundaries=read('data/axel-boundaries-v1/manifest.json')['items'];boots=read('data/axel-demo-v1/boot-workbench-data.json')['items'];items={r['attemptId']:r for r in boots};poses={}
 for r in boundaries:
  aid=r['attemptId'];pose=read('data/pose-batch-v1/'+aid+'.json')
  assert pose['sourceSha256']==r['sourceSha256']==items[aid]['sourceSha256'] and pose['videoId']==r['videoId']
  if rtmw:
   from infer_jump_landmarks import normalize_wholebody,POSE
   raw=read('data/boot-rtmw-v1/'+aid+'.raw.json')
   if raw['weightsSha256']!=sha(POSE) or raw['poseSha256']!=hashes['data/pose-batch-v1/'+aid+'.json']:raise ValueError('RTMW cache weights/box-source provenance mismatch')
   images={f['frameIndex']:f for f in items[aid]['frames']}
   newframes=[]
   for frame in pose['frames']:
    cached=raw['frames'][str(frame['frameIndex'])]
    if cached['sourceFrameSha256']!=images[frame['frameIndex']]['sourceFrameSha256']:raise ValueError('RTMW source-frame mismatch')
    newframes.append(dict(frameIndex=frame['frameIndex'],time=frame['time'],landmarks=normalize_cached_frame(cached)))
   pose=dict(pose,frames=newframes)
  poses[aid]=pose
 vectors,details,extractor=extract_all(root,items,poses,out,hashes)
 records=[];xs=[];ys=[]
 for r in boundaries:
  aid=r['attemptId'];pose=poses[aid];indices=np.array([f['frameIndex'] for f in pose['frames']]);assert np.all(np.diff(indices)==1)
  last=r['boundaries']['lastContact'];first=r['boundaries']['firstContact'];assert last['status']==first['status']=='user_confirmed'
  selection=jitter_slice(aid,indices,last['frameIndex'],first['frameIndex']);pose=dict(pose,frames=pose['frames'][selection]);indices=indices[selection]
  xs.append(combine_features(pose_features(pose),indices,vectors[aid]));ys.append(np.where(indices<=last['frameIndex'],0,np.where(indices<first['frameIndex'],1,2)))
  records.append(dict(attemptId=aid,athlete=r['athleteGroup'],videoId=r['videoId'],sourceSha256=r['sourceSha256'],startFrame=int(indices[0]),endFrame=int(indices[-1]),lastContact=last['frameIndex'],firstContact=first['frameIndex']))
 groups=np.array([r['athlete'] for r in records]);folds=[];baseline=[]
 def fit(indices):
  x=np.concatenate([xs[i] for i in indices]);y=np.concatenate([ys[i] for i in indices]);state=fit_preprocessor(x)
  model=ExtraTreesClassifier(n_estimators=200,min_samples_leaf=5,class_weight='balanced',random_state=20260922,n_jobs=2);model.fit(transform(x,state),y);return model,state
 for train,test in athlete_folds(groups):
  for key in ('videoId','sourceSha256'):assert {records[i][key] for i in train}.isdisjoint({records[i][key] for i in test})
  model,state=fit(train);medians={key:int(np.rint(np.median([records[i][key]-records[i]['startFrame'] for i in train]))) for key in ('lastContact','firstContact')}
  for i in test:
   a,b=decode(model.predict_proba(transform(xs[i],state)));r=records[i];r['predictedLastContact']=r['startFrame']+a;r['predictedFirstContact']=r['startFrame']+b;r['lastContactError']=r['predictedLastContact']-r['lastContact'];r['firstContactError']=r['predictedFirstContact']-r['firstContact']
   baseline.append(dict(attemptId=r['attemptId'],lastContactError=medians['lastContact']+r['startFrame']-r['lastContact'],firstContactError=medians['firstContact']+r['startFrame']-r['firstContact']))
  folds.append(dict(heldOutAthlete=str(groups[test[0]]),trainIndices=train.tolist(),testIndices=test.tolist(),trainingMedianOffsets=medians))
 result=dict(schemaVersion=1,contextJitter=True,poseExtractor=dict(name='RTMW-x WholeBody' if rtmw else 'existing MediaPipe',weightsSha256=sha(POSE) if rtmw else None,missingFootIndex='NaN no alias' if rtmw else 'native MediaPipe'),records=records,metrics={key:metric(records,key) for key in ('lastContact','firstContact')},timingBaseline={key:metric(baseline,key) for key in ('lastContact','firstContact')},baselineRecords=baseline,folds=folds,inputSha256=hashes,extractor=extractor,crops=details,sklearnVersion=sklearn.__version__,
  method='Fixed pose64 + frozen RGB ResNet18 lower-body512; ExtraTrees200,minleaf5,classbalanced,seed20260922; primary SHA256 context jitter identical to phase_contact_pilot; ordered three-state decoder; LOAO athlete/video/source; train-only imputation/scaling; no tuning.',
  limitations=['Known one-jump windows derived from manual contacts even after jitter; no automatic fullprogram discovery','Frozen ImageNet pretraining, not skating-specific fine tuning; crop/pose/missing-image geometry can fail','Manual labels define training states, not model features; no timing/index/identity/protocol features','Previously inspected single event; output remains contact proposal requiring human review'])
 (out/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False));np.savez_compressed(out/'features.npz',**{r['attemptId']:x for r,x in zip(records,xs)})
 model,state=fit(range(len(records)))
 joblib.dump(dict(schemaVersion=1,model=model,preprocessor=state,provenance=result,featureOrder='pose64_then_resnet18_avgpool512',poseCodeSha256=hashlib.sha256(inspect.getsource(pose_features).encode()).hexdigest(),featureCodeSha256=sha(Path(__file__)),status='experimental_known_jump_contact_proposal_not_production'),out/'classifier.joblib')
 return result
def predict_pose(pose_document,image_root,artifact_path,use_duration_prior=False):
 """Consume only this workspace's generated trusted artifact; return review proposal."""
 import joblib,torch,torchvision
 from torchvision.models import resnet18,ResNet18_Weights
 from PIL import Image
 root=Path(__file__).resolve().parents[1];artifact_path=Path(artifact_path).resolve()
 trusted=[root/'work'/name/'classifier.joblib' for name in ('phase-contact-visual','phase-contact-rtmw')]
 if artifact_path not in [p.resolve() for p in trusted]:raise ValueError('Only the locally generated phase-contact-visual artifact is trusted; arbitrary joblib loading is forbidden')
 artifact=joblib.load(artifact_path);provenance=artifact['provenance'];contract=provenance['extractor']
 expected_pose=provenance.get('poseExtractor',dict(name='existing MediaPipe',weightsSha256=None))
 if expected_pose.get('weightsSha256') is not None and pose_document.get('model',{}).get('weightsSha256')!=expected_pose['weightsSha256']:raise ValueError('Input RTMW pose weights differ from contact training')
 if artifact['featureOrder']!='pose64_then_resnet18_avgpool512':raise ValueError('Feature order mismatch')
 if artifact['poseCodeSha256']!=hashlib.sha256(inspect.getsource(pose_features).encode()).hexdigest():raise ValueError('Pose feature code changed since training')
 if contract['cropCodeSha256']!=hashlib.sha256(inspect.getsource(lower_box).encode()).hexdigest() or contract['weightsSha256']!=sha(WEIGHTS):raise ValueError('Visual crop/weights contract differs from training')
 if contract['torchVersion']!=torch.__version__ or contract['torchvisionVersion']!=torchvision.__version__:raise ValueError('Runtime differs from training')
 pose=pose_document;frames=pose['frames'];indices=np.array([f['frameIndex'] for f in frames]);times=np.array([f['time'] for f in frames])
 if len(frames)<3 or not np.all(np.diff(indices)==1) or not np.allclose(np.diff(times),.02,atol=1e-6):raise ValueError('Requires contiguous standardized 50Hz pose frames')
 space=pose['coordinateSpace'];width,height=space['width'],space['height'];image_root=Path(image_root).resolve();images={};hashes={};crop_details=[]
 device='mps' if torch.backends.mps.is_available() else 'cpu';torch.set_num_threads(2)
 model=resnet18(weights=None);model.load_state_dict(torch.load(WEIGHTS,map_location='cpu',weights_only=True));model.fc=torch.nn.Identity();model.eval().to(device)
 preprocess=ResNet18_Weights.IMAGENET1K_V1.transforms()
 if str(preprocess)!=contract['transform']:raise ValueError('Visual transform differs from training')
 batch=[];pending=[]
 def flush():
  if not batch:return
  with torch.inference_mode():values=model(torch.stack(batch).to(device)).cpu().numpy()
  for index,value in zip(pending,values):images[index]=value
  batch.clear();pending.clear()
 for f in frames:
  path=(image_root/f['image']).resolve()
  try:path.relative_to(image_root)
  except ValueError:raise ValueError('Frame image must be inside image_root')
  digest=sha(path)
  if digest!=f['sourceFrameSha256']:raise ValueError('Source frame SHA mismatch')
  hashes[f['image']]=digest
  with Image.open(path) as source:
   image=source.convert('RGB')
   if image.size!=(width,height):raise ValueError('Image/coordinate dimensions mismatch')
   box=lower_box(f['landmarks'],width,height);crop_details.append(dict(frameIndex=f['frameIndex'],crop=box))
   if box is None:continue
   batch.append(preprocess(image.crop(box)));pending.append(f['frameIndex'])
   if len(batch)==16:flush()
 flush()
 if not images:return dict(schemaVersion=1,status='insufficient_lower_body_visibility',reviewRequired=True,predictedLastContact=None,predictedFirstContact=None,sourceSha256=pose['sourceSha256'],modelSha256=sha(artifact_path))
 x=combine_features(pose_features(pose),indices,images);p=artifact['model'].predict_proba(transform(x,artifact['preprocessor']))
 bounds=None
 if use_duration_prior:
  from phase_duration_experiment import duration_bounds,decode_duration
  bounds=duration_bounds(provenance['records'],range(len(provenance['records'])))
  if len(p)<bounds['minAirborneFrames']+2:return dict(schemaVersion=1,status='insufficient_phase_context',reviewRequired=True,predictedLastContact=None,predictedFirstContact=None,sourceSha256=pose['sourceSha256'],modelSha256=sha(artifact_path),durationPrior=bounds)
  a,b=decode_duration(p,bounds['minAirborneFrames'],bounds['maxAirborneFrames'])
 else:a,b=decode(p)
 return dict(schemaVersion=1,status='experimental_contact_review_proposal',durationPrior=bounds,reviewRequired=True,predictedLastContact=int(indices[a]),predictedFirstContact=int(indices[b]),lastContactTime=float(times[a]),firstContactTime=float(times[b]),sourceSha256=pose['sourceSha256'],trainingSourceOverlap=any(r['sourceSha256']==pose['sourceSha256'] for r in provenance['records']),poseExtractor=expected_pose,modelSha256=sha(artifact_path),poseDocumentSha256=hashlib.sha256(json.dumps(pose,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest(),extractor=contract,inputImageSha256=hashes,crops=crop_details,missingCropFrames=len(frames)-len(images),scope='known_single_jump_clip_only',limitations=['Three-state decoder forces one jump; no-jump/multiple-jump inputs unsupported','Training windows are manually cropped; new detector boxes/camera/sequence context remain unvalidated' if expected_pose.get('weightsSha256') else 'Trained on cropped MediaPipe sequences; new RTMW poses are an unvalidated extractor/domain shift','Missing foot_index remains missing and is imputed, no anatomical alias','These contact proposals require review before judging underrotation; no confidence calibration'])

if __name__=='__main__':
 import argparse
 parser=argparse.ArgumentParser();parser.add_argument('--rtmw',action='store_true');parser.add_argument('--predict-pose',type=Path);parser.add_argument('--image-root',type=Path);parser.add_argument('--artifact',type=Path);parser.add_argument('--output',type=Path);args=parser.parse_args()
 if args.predict_pose:
  if not all((args.image_root,args.artifact,args.output)):parser.error('Prediction requires image-root, artifact, output')
  if args.output.exists():raise ValueError('Prediction output already exists')
  r=predict_pose(json.loads(args.predict_pose.read_text()),args.image_root,args.artifact);args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(r,ensure_ascii=False,indent=2,allow_nan=False));print(json.dumps({k:r[k] for k in ('status','predictedLastContact','predictedFirstContact')},ensure_ascii=False))
 else:
  r=run(Path(__file__).resolve().parents[1],args.rtmw);print(json.dumps({k:r[k] for k in ('metrics','timingBaseline')},indent=2))

