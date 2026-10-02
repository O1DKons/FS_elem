"""Fixed full-coarse-context contact study; no pose inference or parameter search."""
import json
from pathlib import Path
import numpy as np
from video_type_model import ROOT,sha
from video_native_type import validated_native
from phase_contact_pilot import decode
from run_rotation_proxy_baseline import fit_preprocessor,transform
OUTPUT=ROOT/'work/full-context-contact-v1'
def features(points,scores,fps):
 p=np.asarray(points,float);s=np.asarray(scores,float)
 if p.shape[1:]!=(17,2) or s.shape!=p.shape[:2] or len(p)<3 or not np.isfinite(fps) or fps<=0:raise ValueError('Invalid native pose')
 hip=p[:,11:13].mean(axis=1);torso=np.linalg.norm(p[:,5:7].mean(axis=1)-hip,axis=1)
 valid=(s[:,[5,6,11,12]]>=.3).all(axis=1)&np.isfinite(torso)&(torso>=2)
 geometry=(p-hip[:,None,:])/np.where(valid,torso,1)[:,None,None]
 geometry[~valid]=np.nan;geometry[s<.3]=np.nan;geometry[~np.isfinite(geometry)]=np.nan
 geometry=geometry.reshape(len(p),34)
 return np.column_stack([geometry,np.gradient(geometry,axis=0)*fps])
def validate_folds(records,folds):
 coverage=[];all_indices=set(range(len(records)))
 for fold in folds:
  tr=fold['trainIndices'];te=fold['testIndices']
  if set(tr)&set(te) or set(tr)|set(te)!=all_indices or len(tr)!=len(set(tr)) or len(te)!=len(set(te)):raise ValueError('Invalid partition')
  for key in ('athlete','videoId','sourceSha256'):
   if {records[i][key] for i in tr}&{records[i][key] for i in te}:raise ValueError('Group leakage')
  coverage.extend(te)
 if sorted(coverage)!=list(range(len(records))):raise ValueError('Heldout coverage mismatch')
def metrics(rows,key):
 e=np.array([r[key+'Error'] for r in rows]);return dict(total=len(e),maeFrames=float(abs(e).mean()),within2Frames=int(sum(abs(e)<=2)),within4Frames=int(sum(abs(e)<=4)),maxAbsoluteError=int(max(abs(e))))
def run():
 import sklearn,joblib
 from sklearn.ensemble import ExtraTreesClassifier
 audit_path=OUTPUT/'mapping-audit.json';audit=json.loads(audit_path.read_text());mapping={r['attemptId']:r for r in audit['records']}
 base_path=ROOT/'work/phase-contact-rtmw/results.json';base=json.loads(base_path.read_text());folds=base['folds'];records=[];xs=[];ys=[]
 rows={r['id']:r for r in json.loads((ROOT/'data/step3-candidates/active-axels.json').read_text())['items']}
 if len(mapping)!=23 or len(base['records'])!=23 or len(folds)!=18:raise ValueError('Dataset size changed')
 for original in base['records']:
  aid=original['attemptId'];r=rows[aid];a=mapping[aid];clip=ROOT/'data/step3-candidates'/r['clip']
  if sha(clip)!=a['clipSha256'] or original['sourceSha256']!=a['sourceSha256'] or r['sourceFrameRange']!=a['sourceFrameRange']:raise ValueError('Input mismatch')
  p,s,fps,indices,provenance,cache_sha=validated_native({'sha256':a['clipSha256']},ROOT/'phase-cache/video-pose-dense-challenge-v2')
  if cache_sha!=a['nativeCacheSha256'] or provenance!=a['nativeProvenance']:raise ValueError('Native cache changed')
  start=a['sourceFrameRange'][0];local={x['contact']:x['localFrame'] for x in a['anchors']}
  for key in ('lastContact','firstContact'):
   if original[key]-start!=local[key]:raise ValueError('Contact mapping changed')
  x=features(p,s,fps);xs.append(x);ys.append(np.where(indices<=local['lastContact'],0,np.where(indices<local['firstContact'],1,2)))
  records.append(dict(attemptId=aid,athlete=original['athlete'],videoId=original['videoId'],sourceSha256=original['sourceSha256'],startFrame=start,frames=len(p),lastContact=original['lastContact'],firstContact=original['firstContact'],finalFrameMappingUnverified=a['finalFrameMappingUnverified']))
 validate_folds(records,folds)
 def fit(ids):
  x=np.concatenate([xs[i] for i in ids]);y=np.concatenate([ys[i] for i in ids]);state=fit_preprocessor(x)
  model=ExtraTreesClassifier(n_estimators=200,min_samples_leaf=5,class_weight='balanced',random_state=20260922,n_jobs=2);model.fit(transform(x,state),y);return model,state
 baseline=[]
 for k,fold in enumerate(folds):
  tr=fold['trainIndices'];te=fold['testIndices'];model,state=fit(tr)
  fractions={key:float(np.median([(records[i][key]-records[i]['startFrame'])/(records[i]['frames']-1) for i in tr])) for key in ('lastContact','firstContact')}
  for i in te:
   pred=decode(model.predict_proba(transform(xs[i],state)));r=records[i];b=dict(attemptId=r['attemptId'])
   for key,local in zip(('lastContact','firstContact'),pred):
    r['predicted'+key[0].upper()+key[1:]]=r['startFrame']+local;r[key+'Error']=r['startFrame']+local-r[key]
    b[key+'Error']=r['startFrame']+int(np.rint(fractions[key]*(r['frames']-1)))-r[key]
   baseline.append(b)
  print(f'fold {k+1}/18',flush=True)
 result=dict(schemaVersion=1,scope='Known-jump coarse-window development contact localization; not fullprogram or underrotation.',records=records,folds=folds,metrics={k:metrics(records,k) for k in ('lastContact','firstContact')},baselineRecords=baseline,timingBaseline={k:metrics(baseline,k) for k in ('lastContact','firstContact')},sklearnVersion=sklearn.__version__,inputSha256={str(audit_path):sha(audit_path),str(base_path):sha(base_path),str(Path(__file__)):sha(__file__),str(ROOT/'scripts/phase_contact_pilot.py'):sha(ROOT/'scripts/phase_contact_pilot.py'),str(ROOT/'scripts/run_rotation_proxy_baseline.py'):sha(ROOT/'scripts/run_rotation_proxy_baseline.py')})
 (OUTPUT/'results.json').write_text(json.dumps(result,indent=2,ensure_ascii=False));model,state=fit(range(23));artifact=OUTPUT/'classifier.joblib';joblib.dump(dict(model=model,state=state,provenance=result,experimental=True),artifact);(OUTPUT/'classifier.sha256').write_text(sha(artifact)+'\n');print(json.dumps(dict(metrics=result['metrics'],baseline=result['timingBaseline'])))
if __name__=='__main__':run()
