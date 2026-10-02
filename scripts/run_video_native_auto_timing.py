"""Frozen native type inference on exported held-out automatic-contact windows."""
import hashlib,inspect,json
from pathlib import Path
import numpy as np
from video_native_type import ROOT,OUTPUT,feature_contract,native_features,validated_native
from video_type_model import sha,fit_classifier,score_classifier
from video_pose_type import evaluate
from extract_dense_pose_type import extract


def main():
 output=ROOT/'work/video-native-auto-timing';manifest_path=output/'manifest.json'
 manifest=json.loads(manifest_path.read_text())
 if not manifest.get('complete') or len(manifest['records'])!=23 or manifest['fixedContextFrames']!=12 or manifest['fps']!=50:raise ValueError('Auto exports incomplete or context changed')
 phase_path=ROOT/'work/phase-contact-rtmw/results.json';oracle_path=ROOT/'work/video-fusion-oracle-timing/results.json'
 if sha(phase_path)!=manifest['contactResultsSha256'] or sha(oracle_path)!=manifest['oracleMetadataSha256']:raise ValueError('Contact/label provenance changed')
 phase=json.loads(phase_path.read_text());lookup={r['attemptId']:r for r in phase['records']};seen=[]
 for fold in phase['folds']:
  tr=fold['trainIndices'];te=fold['testIndices']
  if not set(tr).isdisjoint(te):raise ValueError('Contact index overlap')
  for key in ('athlete','videoId','sourceSha256'):
   if not {phase['records'][i][key] for i in tr}.isdisjoint({phase['records'][i][key] for i in te}):raise ValueError('Contact group/source overlap')
  seen.extend(te)
 if sorted(seen)!=list(range(23)):raise ValueError('Contact test coverage changed')
 model_path=OUTPUT/'classifier.npz'
 with np.load(model_path,allow_pickle=False) as a:
  model={k:a[k] for k in ['classes','mean','std','weights','method']};provenance=json.loads(str(a['provenance']))
 if provenance['contract']!=feature_contract():raise ValueError('Native feature/runtime mismatch')
 if provenance['classifier_code_sha256']!=hashlib.sha256((inspect.getsource(fit_classifier)+inspect.getsource(score_classifier)).encode()).hexdigest():raise ValueError('Classifier implementation changed')
 training={r['sha256'] for r in provenance['records']}
 for row in manifest['records']:
  contact=lookup[row['attemptId']]
  if row['predictedLastContact']!=contact['predictedLastContact'] or row['predictedFirstContact']!=contact['predictedFirstContact'] or row['sourceSha256']!=contact['sourceSha256']:raise ValueError('Automatic contact row mismatch')
  if row['firstSourceFrame']!=contact['predictedLastContact']-12 or row['lastSourceFrame']!=contact['predictedFirstContact']+12:raise ValueError('Automatic crop bounds changed')
  if row['actualFrameCount']!=row['lastSourceFrame']-row['firstSourceFrame']+1:raise ValueError('Automatic crop frame count mismatch')
  if sha(row['clip'])!=row['clipSha256'] or row['clipSha256'] in training:raise ValueError('Clip hash changed or overlaps training')
 manifest_sha=sha(manifest_path);records=[];cache=ROOT/'phase-cache/video-native-auto-timing-v2'
 for row in manifest['records']:
  details={};native_sha=None
  try:
   extract(Path(row['clip']),cache)
   item=dict(sha256=row['clipSha256'])
   p,s,fps,indices,native_provenance,native_sha=validated_native(item,cache)
   if native_provenance!=provenance['native_provenance']:raise ValueError('Native provenance changed')
   if len(p)!=row['actualFrameCount'] or abs(fps-50)>.01:raise ValueError('Decoded native frame count/FPS mismatch')
   feature,details=native_features(p,s,fps,indices)
   prediction=dict(predicted_label='abstain',raw_scores={},extraction_status='insufficient_pose')
   if feature is not None:
    scores=score_classifier(model,feature[None,:])[0]
    prediction.update(predicted_label=str(model['classes'][np.argmax(scores)]),raw_scores={str(c):float(v) for c,v in zip(model['classes'],scores)},extraction_status='ok')
  except Exception as exc:prediction=dict(predicted_label='abstain',raw_scores={},extraction_status='error',error=str(exc))
  if sha(row['clip'])!=row['clipSha256']:raise ValueError('Input changed during inference')
  records.append(dict(attemptId=row['attemptId'],truth=row['truth'],predictedLastContact=row['predictedLastContact'],predictedFirstContact=row['predictedFirstContact'],clipSha256=row['clipSha256'],prediction=prediction,details=details,native_cache_sha256=native_sha))
  result=dict(scope='Positive-only known-jump held-out automatic-contact diagnostic; initial coarse context manually chosen. NOT full-program discovery, specificity, measured rotations or underrotation.',expectedCount=23,complete=len(records)==23,records=records,metrics=evaluate([r['truth'] for r in records],[r['prediction']['predicted_label'] for r in records]),manifestSha256=manifest_sha,modelSha256=sha(model_path),featureContract=feature_contract())
  (output/'results.json').write_text(json.dumps(result,indent=2,allow_nan=False))
  print(json.dumps(dict(completed=len(records),total=23,status=prediction['extraction_status'])),flush=True)
 print(json.dumps(result['metrics'],indent=2))


if __name__=='__main__':main()
