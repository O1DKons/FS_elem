#!/usr/bin/env python3
"""Exploratory athlete-held-out, manually phase-assisted protocol-sign proxy."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np

PAIRS = [('left_shoulder', 'right_shoulder'), ('left_hip', 'right_hip'),
         ('left_ankle', 'right_ankle'), ('left_wrist', 'right_wrist')]
FEATURE_NAMES = ['manual_flight_duration_seconds'] + [f'{a.removeprefix("left_")}_span_torso_normalized_{s}'
                    for a, _ in PAIRS for s in ('mean', 'std')]


def extract_features(pose, boundaries):
    """Only flight pixels/pose and confirmed contact timing; no label/identity input."""
    start, end = boundaries['lastContact'], boundaries['firstContact']
    assert end['frameIndex'] > start['frameIndex'] and end['time'] > start['time']
    values = [[] for _ in PAIRS]
    width, height = pose['coordinateSpace']['width'], pose['coordinateSpace']['height']
    flight = [f for f in pose['frames'] if start['frameIndex'] < f['frameIndex'] < end['frameIndex']]
    for frame in flight:
        points = {p['name']: np.array([p['x']*width, p['y']*height]) for p in frame['landmarks']
                  if p.get('confidence', 0) >= .5 and np.isfinite([p['x'],p['y']]).all()}
        names = ['left_shoulder','right_shoulder','left_hip','right_hip']
        if not all(n in points for n in names):
            continue
        torso = np.linalg.norm((points[names[0]]+points[names[1]]-points[names[2]]-points[names[3]])/2)
        if torso < 1:
            continue
        for bucket, (left,right) in zip(values, PAIRS):
            if left in points and right in points:
                bucket.append(float(np.linalg.norm(points[left]-points[right])/torso))
    features = [end['time']-start['time']]
    for bucket in values:
        features.extend([float(np.mean(bucket)),float(np.std(bucket))] if bucket else [np.nan,np.nan])
    return np.array(features), dict(flightFramesAvailable=len(flight),
        validGeometryFrames={left:len(v) for (left,_),v in zip(PAIRS,values)})


def athlete_folds(groups):
    groups = np.asarray(groups)
    for group in sorted(set(groups)):
        train, test = np.flatnonzero(groups != group), np.flatnonzero(groups == group)
        assert set(groups[train]).isdisjoint(groups[test])
        yield train, test


def fit_preprocessor(x):
    valid = np.isfinite(x)
    count = valid.sum(axis=0)
    mean = np.divide(np.where(valid,x,0).sum(axis=0), count, out=np.zeros(x.shape[1]), where=count>0)
    filled = np.where(valid,x,mean)
    scale = filled.std(axis=0)
    scale[scale < 1e-12] = 1
    return dict(mean=mean,scale=scale)


def transform(x,state):
    return (np.where(np.isfinite(x),x,state['mean'])-state['mean'])/state['scale']


def metrics(truth,predicted):
    confusion = [[sum(int(a)==i and int(b)==j for a,b in zip(truth,predicted)) for j in (0,1)] for i in (0,1)]
    recalls = [confusion[i][i]/sum(confusion[i]) if sum(confusion[i]) else None for i in (0,1)]
    return dict(n=len(truth),correct=sum(int(a)==int(b) for a,b in zip(truth,predicted)),
        accuracy=sum(int(a)==int(b) for a,b in zip(truth,predicted))/len(truth),
        balancedAccuracy=sum(recalls)/2 if None not in recalls else None,
        recallUnmarked=recalls[0],recallMarked=recalls[1],confusionTrueRowsPredictedColumns=confusion)


def evaluate(x,y,groups,majority=False):
    predictions = np.zeros(len(y),dtype=int)
    folds = []
    for train,test in athlete_folds(groups):
        # Every fitted quantity uses train only. No hyperparameter search.
        state = fit_preprocessor(x[train])
        trainx, testx = transform(x[train],state), transform(x[test],state)
        if majority or len(set(y[train])) < 2:
            predictions[test] = int(np.sum(y[train]==1)>np.sum(y[train]==0))
        else:
            centroids = np.array([trainx[y[train]==label].mean(axis=0) for label in (0,1)])
            predictions[test] = ((testx[:,None,:]-centroids[None,:,:])**2).sum(axis=2).argmin(axis=1)
        folds.append(dict(heldOutAthlete=groups[test[0]],trainIndices=train.tolist(),testIndices=test.tolist(),
            trainingClassCounts=[int(sum(y[train]==i)) for i in (0,1)],
            preprocessor={k:v.tolist() for k,v in state.items()}))
    return dict(metrics=metrics(y,predictions),predictions=predictions.tolist(),folds=folds)


def run(root):
    hashes = {}
    def read(relative):
        path=root/relative
        hashes[relative]=hashlib.sha256(path.read_bytes()).hexdigest()
        return json.loads(path.read_text())
    manifest=read('data/axel-boundaries-v1/manifest.json')['items']
    records=[]
    features=[]
    for row in manifest:
        code=row['protocolCode'].split('+')[0]
        if code not in ('2A','2A<','2A<<'):
            continue
        pose=read(f"data/pose-batch-v1/{row['attemptId']}.json")
        assert pose['sourceSha256']==row['sourceSha256'] and pose['videoId']==row['videoId']
        assert all(row['boundaries'][k]['status']=='user_confirmed' for k in ('lastContact','firstContact'))
        f, quality=extract_features(pose,row['boundaries'])
        features.append(f)
        records.append(dict(attemptId=row['attemptId'],athlete=row['athleteGroup'],videoId=row['videoId'],
            protocolComponent=code,target=int('<' in code),featureValues=[float(v) if np.isfinite(v) else None for v in f],
            quality=quality))
    x=np.array(features);y=np.array([r['target'] for r in records]);groups=[r['athlete'] for r in records]
    for train,test in athlete_folds(groups):
        assert {records[i]['videoId'] for i in train}.isdisjoint(records[i]['videoId'] for i in test)
    variants={
        'training_majority':evaluate(x[:,:1],y,groups,majority=True),
        'manual_duration_only':evaluate(x[:,:1],y,groups),
        'flight_pose_geometry_only':evaluate(x[:,1:],y,groups),
        'manual_duration_and_flight_pose':evaluate(x,y,groups)}
    return dict(schemaVersion=1,scope='PROTOCOL proxy, not true underrotation; manually phase-assisted, not full-program inference; exploratory single-event LOAO',
        classes={'0':'protocol 2A unmarked, not independently confirmed clean','1':'protocol 2A< or 2A<<'},
        method='Euclidean nearest class centroid; equal class decision distances; training-only mean imputation and standardization; confidence >=0.5; no tuning; ties class0',
        featureNames=FEATURE_NAMES,inputSha256=hashes,records=records,variants=variants,
        limitations=['22 attempts,17 athletes,one event; all previously inspected; no independent test',
            'Protocol marks may be noisy or misassociated; no measured rotation degrees',
            'Human contact boundaries used even in geometry-only model; cached pose may fail',
            'Repeated athletes are grouped, but event/camera conditions remain shared',
            'No calibrated probability or deployment accuracy claim; no preprocessing fitted across folds'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output',type=Path,default=Path('work/step27-rotation-proxy/results.json'))
    args=parser.parse_args();root=args.root.resolve();result=run(root)
    output=args.output if args.output.is_absolute() else root/args.output
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps({key:value['metrics'] for key,value in result['variants'].items()},indent=2))

if __name__=='__main__':
    main()
