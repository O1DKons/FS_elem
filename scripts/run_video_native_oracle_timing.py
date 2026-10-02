"""Frozen native model on existing fixed oracle clips; no exports or training."""
import hashlib,inspect,json
from pathlib import Path
import numpy as np
from video_native_type import ROOT,OUTPUT,feature_contract,native_features,validated_native
from video_type_model import sha,fit_classifier,score_classifier
from video_pose_type import evaluate
from extract_dense_pose_type import extract


def main():
 import cv2
 prior_path=ROOT/'work/video-fusion-oracle-timing/results.json'
 contacts_path=ROOT/'data/axel-demo-v1/rotation-review-data.json'
 prior=json.loads(prior_path.read_text());contacts=json.loads(contacts_path.read_text())
 lookup={i['attemptId']:i for i in contacts['items']}
 if not prior.get('complete') or len(prior['records'])!=23 or len(lookup)!=23:raise ValueError('Expected completed23 oracle exports')
 model_path=OUTPUT/'classifier.npz'
 with np.load(model_path,allow_pickle=False) as a:
  model={k:a[k] for k in ['classes','mean','std','weights','method']};provenance=json.loads(str(a['provenance']))
 if provenance['contract']!=feature_contract():raise ValueError('Feature/runtime contract mismatch')
 expected=hashlib.sha256((inspect.getsource(fit_classifier)+inspect.getsource(score_classifier)).encode()).hexdigest()
 if expected!=provenance['classifier_code_sha256']:raise ValueError('Classifier implementation mismatch')
 output=ROOT/'work/video-native-oracle-timing';output.mkdir(parents=True,exist_ok=True)
 cache=ROOT/'phase-cache/video-native-oracle-timing-v2';verified={};inputs=[]
 training={r['sha256'] for r in provenance['records']}
 for row in prior['records']:
  item=lookup[row['attemptId']];start=item['lastContact']-12;end=item['firstContact']+12
  source=ROOT/'data/live/media'/(item['videoId']+'.mp4')
  if source not in verified:verified[source]=sha(source)
  if verified[source]!=item['sourceSha256'] or row['sourceSha256']!=item['sourceSha256']:raise ValueError('Source hash mismatch')
  if row['firstSourceFrame']!=start or row['lastSourceFrame']!=end or row['expectedFrameCount']!=end-start+1:raise ValueError('Oracle bounds changed')
  clip=ROOT/'work/video-fusion-oracle-timing/clips'/(row['attemptId']+'.mp4');digest=sha(clip)
  if digest!=row['prediction']['video_sha256'] or digest in training:raise ValueError('Oracle clip changed or appears in training')
  cap=cv2.VideoCapture(str(clip));fps=cap.get(cv2.CAP_PROP_FPS);count=0
  try:
   while cap.read()[0]:count+=1
  finally:cap.release()
  if abs(fps-50)>.01 or count!=end-start+1 or count!=row['actualFrameCount']:raise ValueError('Actual oracle frame count/FPS mismatch')
  inputs.append(dict(attemptId=row['attemptId'],truth=row['truth'],clip=str(clip),sha256=digest,sourceSha256=item['sourceSha256'],firstSourceFrame=start,lastSourceFrame=end,actualFrameCount=count,fps=fps))
 # Freeze the verified inputs before any new model inference.
 archive=dict(scope='ORACLE TIMING fixed pre-existing ±12frame clips; positive-only; no automatic localization or measured rotations.',records=inputs,priorSha256=sha(prior_path),contactsSha256=sha(contacts_path),modelSha256=sha(model_path))
 (output/'verified-inputs.json').write_text(json.dumps(archive,indent=2))
 records=[]
 for row in inputs:
  details={};native_sha=None
  try:
   extract(Path(row['clip']),cache)
   p,s,fps,indices,native_provenance,native_sha=validated_native(row,cache)
   if native_provenance!=provenance['native_provenance']:raise ValueError('Native provenance mismatch')
   feature,details=native_features(p,s,fps,indices)
   prediction=dict(predicted_label='abstain',raw_scores={},extraction_status='insufficient_pose')
   if feature is not None:
    scores=score_classifier(model,feature[None,:])[0]
    prediction.update(predicted_label=str(model['classes'][np.argmax(scores)]),raw_scores={str(c):float(v) for c,v in zip(model['classes'],scores)},extraction_status='ok')
  except Exception as exc:prediction=dict(predicted_label='abstain',raw_scores={},extraction_status='error',error=str(exc))
  if sha(row['clip'])!=row['sha256']:raise ValueError('Oracle input changed during inference')
  records.append(dict(**row,prediction=prediction,details=details,native_cache_sha256=native_sha))
  result=dict(scope=archive['scope'],expectedCount=23,complete=len(records)==23,records=records,metrics=evaluate([r['truth'] for r in records],[r['prediction']['predicted_label'] for r in records]),verifiedInputSha256=sha(output/'verified-inputs.json'),modelSha256=sha(model_path),featureContract=feature_contract())
  (output/'results.json').write_text(json.dumps(result,indent=2,allow_nan=False))
  print(json.dumps(dict(completed=len(records),total=23,status=prediction['extraction_status'])),flush=True)
 print(json.dumps(result['metrics'],indent=2))


if __name__=='__main__':main()
