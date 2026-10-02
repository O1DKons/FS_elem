"""Final cached pose/video fusion development experiment, no new inference."""
import hashlib
import argparse
import subprocess
import sys
import inspect
import json
from pathlib import Path
import numpy as np
from video_type_model import ROOT, sha
from video_pose_type import evaluate


def pose_descriptor(points,scores):
    p=np.asarray(points,float);s=np.asarray(scores,float)
    if p.shape!=(32,17,2) or s.shape!=(32,17):raise ValueError('Expected32 COCO17 frames')
    center=p[:,11:13].mean(axis=1);up=p[:,5:7].mean(axis=1)-center
    length=np.linalg.norm(up,axis=1)
    torso_ok=(s[:,[5,6,11,12]]>=.3).all(axis=1)&np.isfinite(length)&(length>=2)
    unit=up/np.where(torso_ok,length,np.nan)[:,None]
    side=np.stack([-unit[:,1],unit[:,0]],axis=1)
    relative=(p-center[:,None,:])/np.where(torso_ok,length,np.nan)[:,None,None]
    coords=np.stack([np.sum(relative*side[:,None,:],axis=2),np.sum(relative*unit[:,None,:],axis=2)],axis=2)
    valid=torso_ok[:,None]&(s>=.3)&np.isfinite(coords).all(axis=2)
    coords[~valid]=np.nan
    confidence=np.where(valid,np.clip(s,0,1),0)
    differences=coords[1:]-coords[:-1]
    return np.r_[coords.ravel(),differences.ravel(),confidence.ravel()],int(sum(torso_ok))


def fit_preprocessing(x):
    finite=np.isfinite(x);count=finite.sum(axis=0)
    mean=np.where(finite,x,0).sum(axis=0)/np.maximum(count,1)
    filled=np.where(finite,x,mean)
    std=filled.std(axis=0);std[std<1e-8]=1
    return dict(mean=mean,std=std)


def preprocess(x,parameters):
    return (np.where(np.isfinite(x),x,parameters['mean'])-parameters['mean'])/parameters['std']


def fit_model(x,y,method):
    from sklearn.linear_model import Ridge
    from sklearn.ensemble import ExtraTreesClassifier
    params=fit_preprocessing(x);z=preprocess(x,params);classes=np.unique(y)
    if method=='ridge':
        model=Ridge(alpha=10,solver='lsqr',tol=1e-6,max_iter=1000)
        balance=np.array([len(y)/(len(classes)*sum(y==c)) for c in y])
        model.fit(z,(y[:,None]==classes[None,:]).astype(float),sample_weight=balance)
    elif method=='extra_trees':
        model=ExtraTreesClassifier(n_estimators=200,min_samples_leaf=3,class_weight='balanced',random_state=0,n_jobs=2)
        model.fit(z,y)
    else:raise ValueError(method)
    return dict(preprocessing=params,model=model,classes=classes,method=method)


def predict(model,x):
    z=preprocess(x,model['preprocessing'])
    if model['method']=='ridge':return model['classes'][model['model'].predict(z).argmax(axis=1)]
    return model['model'].predict(z)


def load_features(records,video_provenance,pose_provenance,cache_root=None):
    cache_root=Path(cache_root or ROOT/'phase-cache')
    features=[];details=[]
    for record in records:
        digest=record['sha256'];video=cache_root/'video-type'/(digest+'.npz');pose=cache_root/'video-pose-type'/(digest+'.npz')
        error=None;valid_frames=0
        try:
            with np.load(video,allow_pickle=False) as a:
                if str(a['source_sha256'])!=digest or json.loads(str(a['provenance']))!=video_provenance:
                    raise ValueError('Video feature cache provenance mismatch')
                appearance=a['feature']
            with np.load(pose,allow_pickle=False) as a:
                if str(a['source_sha256'])!=digest or json.loads(str(a['provenance']))!=pose_provenance:
                    raise ValueError('Pose cache provenance mismatch')
                motion,valid_frames=pose_descriptor(a['points'],a['scores'])
            feature=np.r_[motion,appearance]
            if appearance.shape!=(512,) or not np.isfinite(appearance).all():raise ValueError('Invalid video feature')
        except (FileNotFoundError,ValueError,KeyError) as exc:
            feature=np.full(3198,np.nan);error=str(exc)
        features.append(feature)
        details.append(dict(file=record['file'],sha256=digest,truth=record['truth'],group=record['group'],
                            valid=error is None,valid_torso_frames=valid_frames,error=error))
    return np.stack(features),details


def main():
    import sklearn,joblib
    appearance_path=ROOT/'work/video-type-pilot-v1/results.json'
    pose_path=ROOT/'work/video-pose-type-v1/results.json'
    appearance=json.loads(appearance_path.read_text());pose=json.loads(pose_path.read_text())
    assert appearance['folds']==pose['folds']
    assert [r['sha256'] for r in appearance['records']]==[r['sha256'] for r in pose['records']]
    x,records=load_features(appearance['records'],appearance['extractor_provenance'],pose['provenance'])
    y=np.array([r['truth'] for r in records]);valid=np.array([r['valid'] for r in records]);variants={}
    for method in ['ridge','extra_trees']:
        prediction=np.full(len(y),'abstain',dtype=object)
        for fold in appearance['folds']:
            tr=np.array(fold['train']);te=np.array(fold['test']);tr=tr[valid[tr]];te=te[valid[te]]
            if not len(tr) or not len(te):continue
            model=fit_model(x[tr],y[tr],method);prediction[te]=predict(model,x[te])
        variants[method]=dict(metrics=evaluate(y,prediction),predictions=prediction.tolist())
    result=dict(method='Fixed normalizedfullpose+motion+confidence+R3D; Ridge10 primary; ExtraTrees200/minleaf3 comparison.',
                scope='Development model comparison only; same inspected190/folds; officialtest untouched.',
                variants=variants,records=records,folds=appearance['folds'],feature_dimension=x.shape[1],
                feature_code_sha256=hashlib.sha256(inspect.getsource(pose_descriptor).encode()).hexdigest(),
                inputs={str(appearance_path):sha(appearance_path),str(pose_path):sha(pose_path)},
                video_provenance=appearance['extractor_provenance'],pose_provenance=pose['provenance'],
                sklearn_version=sklearn.__version__)
    output=ROOT/'work/video-fusion-type-v1';output.mkdir(parents=True,exist_ok=True)
    (output/'results.json').write_text(json.dumps(result,indent=2))
    joblib.dump(dict(**fit_model(x[valid],y[valid],'ridge'),provenance=result),output/'classifier.joblib')
    (output/'classifier.sha256').write_text(sha(output/'classifier.joblib')+'\n')
    print(json.dumps({k:v['metrics'] for k,v in variants.items()},indent=2))


TRUSTED_ARTIFACT=ROOT/'work/video-fusion-type-v1/classifier.joblib'

def load_trusted_artifact(artifact_path):
    import sklearn,joblib
    expected=TRUSTED_ARTIFACT.with_suffix('.sha256').read_text().strip()
    if sha(artifact_path)!=expected:
        raise ValueError('Fusion artifact does not match the locally registered trusted SHA256')
    model=joblib.load(artifact_path)
    provenance=model['provenance']
    if provenance['feature_code_sha256']!=hashlib.sha256(inspect.getsource(pose_descriptor).encode()).hexdigest():
        raise ValueError('Fusion feature implementation mismatch')
    if provenance['sklearn_version']!=sklearn.__version__:
        raise ValueError('Fusion sklearn runtime mismatch')
    for path,digest in provenance['inputs'].items():
        if sha(path)!=digest:raise ValueError('Fusion training provenance file changed')
    return model

def predict_clip(video_path,artifact_path=TRUSTED_ARTIFACT,cache_dir=None):
    from video_type_model import embedding
    model=load_trusted_artifact(artifact_path);provenance=model['provenance']
    video_path=Path(video_path).resolve();digest=sha(video_path)
    cache_root=Path(cache_dir or ROOT/'phase-cache')
    embedding(video_path,cache_root/'video-type')
    pose_path=cache_root/'video-pose-type'/(digest+'.npz')
    needs_pose=True
    if pose_path.exists():
        with np.load(pose_path,allow_pickle=False) as a:
            needs_pose=(str(a['source_sha256'])!=digest or json.loads(str(a['provenance']))!=provenance['pose_provenance'])
    if needs_pose:
        python=ROOT/'work/step23-rtmpose/venv/bin/python'
        code="import sys;sys.path.insert(0,'scripts');from video_pose_type import extract_pose;extract_pose(sys.argv[1],sys.argv[2])"
        completed=subprocess.run([str(python),'-c',code,str(video_path),str(cache_root/'video-pose-type')],cwd=ROOT,capture_output=True,text=True,timeout=180)
        if completed.returncode:
            raise RuntimeError('Pose extraction failed: '+completed.stderr[-1500:])
    x,records=load_features([dict(sha256=digest,file=str(video_path),truth='',group='')],
                           provenance['video_provenance'],provenance['pose_provenance'],cache_root)
    if not records[0]['valid']:raise ValueError(records[0]['error'])
    z=preprocess(x,model['preprocessing']);scores=model['model'].predict(z)[0]
    return dict(predicted_label=str(model['classes'][np.argmax(scores)]),
                raw_scores={str(c):float(v) for c,v in zip(model['classes'],scores)},
                classes=model['classes'].tolist(),extraction_status='ok',scope='short_single_element_clip',
                video_sha256=digest,valid_torso_frames=records[0]['valid_torso_frames'],
                limitation='Development type/count candidate only; no underrotation or physical rotation measurement.')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--predict');parser.add_argument('--artifact',default=str(TRUSTED_ARTIFACT))
    args=parser.parse_args()
    if args.predict:print(json.dumps(predict_clip(args.predict,args.artifact),indent=2))
    else:main()
