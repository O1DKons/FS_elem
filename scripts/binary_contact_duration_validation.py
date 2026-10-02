"""Validate fixed pivot classifier under athlete-out duration-constrained contact proposals."""
import hashlib,json
from pathlib import Path
import numpy as np
from boot_detection import landing_candidates
from binary_pivot import pivot_features,FEATURES
from run_rotation_proxy_baseline import athlete_folds,fit_preprocessor,transform,metrics

def at_contact(item,contact):
 # Discard manually anchored landing-role rows; reconstruct only from raw side candidates.
 frames=[dict(f,candidates=[c for c in f['candidates'] if c['side'] in ('left','right')]) for f in item['frames']]
 return pivot_features(dict(firstContact=int(contact),frames=landing_candidates(frames,int(contact))))

def run(root):
 hashes={}
 def read(path):
  raw=(root/path).read_bytes();hashes[path]=hashlib.sha256(raw).hexdigest();return json.loads(raw)
 phase=read('work/phase-duration-v1/results.json');base=read('work/binary_pivot/results.json');manifest=read('data/axel-demo-v1/boot-workbench-data.json');items={r['attemptId']:r for r in manifest['items']}
 for source in (phase,base):
  for path,digest in source['inputSha256'].items():
   actual=hashlib.sha256((root/path).read_bytes()).hexdigest()
   if actual!=digest:raise ValueError('Stale input '+path)
   hashes[path]=actual
 lookup={r['attemptId']:(i,r) for i,r in enumerate(phase['records'])};records=[];vectors={name:[] for name in ('manual','automatic','manual_minus4','manual_plus4')};phase_audit=[]
 for r in base['records']:
  aid=r['attemptId'];item=items[aid];pi,pr=lookup[aid]
  if pr['sourceSha256']!=r['sourceSha256'] or pr['athlete']!=r['athlete'] or pr['firstContact']!=item['firstContact']:raise ValueError('Phase/binary source correspondence mismatch')
  folds=[f for f in phase['folds'] if pi in f['testIndices']]
  if len(folds)!=1:raise ValueError('Phase prediction must have exactly one held-out fold')
  fold=folds[0]
  if fold['heldOutAthlete']!=r['athlete']:raise ValueError('Wrong held-out phase athlete')
  for j in fold['trainIndices']:
   trained=phase['records'][j]
   if any(trained[k]==r[k] for k in ('athlete','videoId','sourceSha256')):raise ValueError('Phase prediction trained on binary test identity/source')
  phase_audit.append(dict(attemptId=aid,phaseRecordIndex=pi,heldOutAthlete=fold['heldOutAthlete'],phaseTrainIndices=fold['trainIndices'],phaseTestIndices=fold['testIndices']))
  contacts=dict(manual=item['firstContact'],automatic=pr['predictedFirstContact'],manual_minus4=item['firstContact']-4,manual_plus4=item['firstContact']+4)
  quality={}
  for name,contact in contacts.items():
   v=at_contact(item,contact);vectors[name].append(v);quality[name]=dict(visibleFrames=int(round(v[0]*11)),adjacentIntervals=int(round(v[1]*10)),missingFeatureCount=int(sum(~np.isfinite(v))))
  records.append(dict(**r,contacts=contacts,quality=quality,contactError=contacts['automatic']-contacts['manual']))
 matrices={name:np.asarray(v) for name,v in vectors.items()};original=np.asarray(base['features'],dtype=float)
 if not np.allclose(matrices['manual'],original,equal_nan=True):raise ValueError('Recomputed manual landing roles changed the frozen baseline features')
 y=np.array([r['truth'] for r in records]);groups=np.array([r['athlete'] for r in records]);predictions={name:np.zeros(len(records),dtype=int) for name in matrices};folds=[]
 for train,test in athlete_folds(groups):
  state=fit_preprocessor(matrices['manual'][train]);trainx=transform(matrices['manual'][train],state);present=np.unique(y[train]);centers=np.array([trainx[y[train]==c].mean(0) for c in present])
  for name,matrix in matrices.items():
   query=transform(matrix[test],state);predictions[name][test]=present[((query[:,None,:]-centers[None,:,:])**2).sum(2).argmin(1)]
  folds.append(dict(heldOutAthlete=str(groups[test[0]]),trainIndices=train.tolist(),testIndices=test.tolist(),trainingContacts='manual_only'))
 if predictions['manual'].tolist()!=base['variants']['centroid']['predictions']:raise ValueError('Frozen manual centroid baseline did not reproduce')
 result=dict(schemaVersion=1,records=records,featureNames=FEATURES,features={name:[[float(v) if np.isfinite(v) else None for v in row] for row in a] for name,a in matrices.items()},predictions={k:v.tolist() for k,v in predictions.items()},metrics={k:metrics(y,v) for k,v in predictions.items()},switchesFromManual={k:int(sum(v!=predictions['manual'])) for k,v in predictions.items()},phaseLeakageAudit=phase_audit,folds=folds,inputSha256=hashes,
  method='Frozen pivot centroid trained only on manual-contact features within each athlete-out fold. Test automatic firstContact from same-athlete-excluded RTMW phase fold with train-only duration constraint. Landing roles recomputed from raw left/right candidates at test proposed contact. No excluded low-coverage attempts; train-only preprocessing. Fixed manual±4-frame sensitivity, no tuning.',
  limitations=['Legacy50Hz OOF validation, separate from new runtime deduplicated sampling; same20 expert labels and known-jump pose windows derived from manual contacts','Not arbitrary video, fullprogram search, independent event or measured rotation degrees','Training uses manual contacts; this experiment measures test-time contact error, not cross-fitted auto-contact training','Existing side candidates/model crops are cached; newvideo detection/pose domain effects not measured','Insufficient coverage is reported and imputed, not hidden; raw classifier does not abstain automatically'])
 out=root/'work/binary-contact-duration-validation';out.mkdir(exist_ok=True);(out/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False));return result
if __name__=='__main__':
 r=run(Path(__file__).resolve().parents[1]);print(json.dumps(dict(metrics=r['metrics'],switches=r['switchesFromManual']),indent=2))
