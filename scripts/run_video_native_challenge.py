"""Frozen native-time model on the same26 whole coarse clips; no window search."""
import argparse
import hashlib
import inspect
import json
import re
from pathlib import Path
import numpy as np
from video_native_type import ROOT,OUTPUT,feature_contract,native_features,validated_native,pilot_items
from video_type_model import CLASSES,sha,fit_classifier,score_classifier
from video_pose_type import evaluate


def challenge_rows():
    paths=['data/step3-candidates/active-axels.json','data/step3-candidates/manifest.json','data/step3-candidates/user-review.json']
    active,manifest,review=[json.loads((ROOT/p).read_text()) for p in paths]
    rows=[]
    for r in active['items']:
        match=re.match(r'^([1234]A)',r['protocolCode'])
        if not match or match.group(1) not in CLASSES:raise ValueError('Unexpected nominal target')
        rows.append(dict(attemptId=r['id'],truth=match.group(1),truthSource='Confirmed Axel clip; nominal protocol type, not measured rotation.',
                         path=str(ROOT/'data/step3-candidates'/r['clip']),sha256=r['clipSha256']))
    lookup={r['id']:r for r in manifest['items']}
    for aid in review['rejectedNoJump']+review['outOfScope']:
        r=lookup[aid]
        rows.append(dict(attemptId=aid,truth='other',truthSource='Explicit user no-jump or non-Axel review.',
                         path=str(ROOT/'data/step3-candidates'/r['clip']),sha256=r['clipSha256']))
    baseline_path=ROOT/'work/video-type-challenge/results.json';baseline=json.loads(baseline_path.read_text())
    expected=[(r['attemptId'],r['truth'],r['prediction']['video_sha256']) for r in baseline['records']]
    if len(rows)!=26 or [(r['attemptId'],r['truth'],r['sha256']) for r in rows]!=expected:
        raise ValueError('Challenge rows/order/labels/SHA changed from original26')
    for r in rows:
        if sha(r['path'])!=r['sha256']:raise ValueError('Challenge video SHA mismatch')
    return rows,{p:sha(ROOT/p) for p in paths}|{str(baseline_path):sha(baseline_path)}


def assert_disjoint(rows,training_hashes):
    if any(r['sha256'] in training_hashes for r in rows):raise ValueError('Exact training video appears in challenge')


def extract_only(cache,output):
    from extract_dense_pose_type import extract
    rows,input_hashes=challenge_rows()
    manifest=ROOT/'data/skatingverse-pilot-v1/manifest.json'
    training,_=pilot_items(manifest);assert_disjoint(rows,{i['sha256'] for i in training})
    cache=Path(cache);output=Path(output);output.mkdir(parents=True,exist_ok=True);records=[]
    for row in rows:
        record=dict(attemptId=row['attemptId'],source_sha256=row['sha256'],status='error')
        try:
            path=extract(Path(row['path']),cache)
            points,scores,fps,indices,provenance,digest=validated_native(row,cache)
            record.update(status='ok',frames=len(points),fps=fps,cache=str(path),cache_sha256=digest,provenance=provenance)
        except Exception as exc:record['error']=str(exc)
        records.append(record)
        progress=dict(scope='Native whole-clip extraction only; no classifier/predictions.',records=records,expectedCount=26,
                      complete=len(records)==26,successfulCount=sum(r['status']=='ok' for r in records),training_started=False,
                      inputSha256={**input_hashes,str(manifest):sha(manifest)})
        (output/'extraction-progress.json').write_text(json.dumps(progress,indent=2,ensure_ascii=False,allow_nan=False))
        print(json.dumps(dict(completed=len(records),total=26,status=record['status'])),flush=True)


def run(model_path,cache,output):
    from extract_dense_pose_type import extract
    with np.load(model_path,allow_pickle=False) as artifact:
        model={k:artifact[k] for k in ['classes','mean','std','weights','method']}
        provenance=json.loads(str(artifact['provenance']))
    if provenance['contract']!=feature_contract():raise ValueError('Native feature/runtime contract mismatch')
    expected_classifier=hashlib.sha256((inspect.getsource(fit_classifier)+inspect.getsource(score_classifier)).encode()).hexdigest()
    if provenance['classifier_code_sha256']!=expected_classifier:raise ValueError('Classifier implementation changed')
    rows,input_hashes=challenge_rows();assert_disjoint(rows,{r['sha256'] for r in provenance['records']})
    output=Path(output);output.mkdir(parents=True,exist_ok=True);cache=Path(cache);records=[]
    for row in rows:
        details={};native_sha=None
        try:
            path=extract(Path(row['path']),cache)
            points,scores,fps,indices,native_provenance,native_sha=validated_native(row,cache)
            if native_provenance!=provenance['native_provenance']:raise ValueError('Native pose provenance changed')
            feature,details=native_features(points,scores,fps,indices)
            prediction=dict(predicted_label='abstain',raw_scores={},classes=model['classes'].tolist(),extraction_status='insufficient_pose',video_sha256=row['sha256'])
            if feature is not None:
                scores=score_classifier(model,feature[None,:])[0]
                prediction.update(predicted_label=str(model['classes'][np.argmax(scores)]),raw_scores={str(c):float(v) for c,v in zip(model['classes'],scores)},extraction_status='ok')
        except Exception as exc:
            prediction=dict(predicted_label='abstain',raw_scores={},extraction_status='error',error=str(exc),video_sha256=row['sha256'])
        records.append(dict(attemptId=row['attemptId'],truth=row['truth'],truthSource=row['truthSource'],prediction=prediction,
                            details=details,native_cache_sha256=native_sha))
        result=dict(scope='Same26whole coarse clips; frozen native-time model; no sliding windows or tuning. Nominal type only, no measured rotations or underrotation. Exact source hashes disjoint from training; differently encoded source/athlete overlap unverified.',
                    expectedCount=26,complete=len(records)==26,records=records,
                    metrics=evaluate([r['truth'] for r in records],[r['prediction']['predicted_label'] for r in records]),
                    inputSha256=input_hashes,modelSha256=sha(model_path),featureContract=feature_contract())
        (output/'results.json').write_text(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False))
        print(json.dumps(dict(completed=len(records),total=26,status=prediction['extraction_status'])),flush=True)
    print(json.dumps(result['metrics'],indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--model',type=Path,default=OUTPUT/'classifier.npz')
    parser.add_argument('--cache',type=Path,default=ROOT/'phase-cache/video-pose-dense-challenge-v2')
    parser.add_argument('--output',type=Path,default=ROOT/'work/video-native-type-challenge')
    parser.add_argument('--extract-only',action='store_true')
    args=parser.parse_args()
    if args.extract_only:extract_only(args.cache,args.output)
    else:run(args.model,args.cache,args.output)
