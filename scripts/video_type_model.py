"""Frozen R3D18 short-clip pilot. Fixed ridge alpha=10; no official test access."""
import argparse
import hashlib
import json
import inspect
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CLASSES = ['1A', '2A', '3A', 'other']
LABEL_MAP = {21:'1A',2:'2A',9:'3A',0:'other',8:'other',1:'other',10:'other',11:'other',3:'other',4:'other',5:'other'}
EXTRACTOR = 'torchvision-r3d18-KINETICS400_V1-16uniform-rgb-v1'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def grouped_folds(groups, count=5):
    ordered = sorted(set(groups), key=lambda g: hashlib.sha256(str(g).encode()).hexdigest())
    if len(ordered) < 2:
        raise ValueError('At least two independent groups required')
    assignment = {g: i % min(count, len(ordered)) for i, g in enumerate(ordered)}
    return [(np.array([i for i,g in enumerate(groups) if assignment[g] != f]),
             np.array([i for i,g in enumerate(groups) if assignment[g] == f]))
            for f in range(min(count,len(ordered)))]


def fit_classifier(x, y, method='ridge'):
    classes = np.unique(y)
    mean = x.mean(axis=0)
    std = x.std(axis=0)
    std[std < 1e-8] = 1
    z = (x-mean)/std
    if method == 'centroid':
        weights = np.stack([z[y==c].mean(axis=0) for c in classes])
    elif method == 'ridge':
        design = np.column_stack([z, np.ones(len(z))])
        target = (y[:,None] == classes[None,:]).astype(float)
        balance = np.array([len(y)/(len(classes)*sum(y==c)) for c in y])
        penalty = np.eye(design.shape[1])*10
        penalty[-1,-1] = 0
        weights = np.linalg.solve(design.T@(balance[:,None]*design)+penalty,
                                  design.T@(balance[:,None]*target))
    else:
        raise ValueError(method)
    return dict(classes=classes, mean=mean, std=std, weights=weights, method=np.array(method))


def score_classifier(model, x):
    z=(np.asarray(x)-model['mean'])/model['std']
    if str(model['method']) == 'ridge':
        return np.column_stack([z,np.ones(len(z))])@model['weights']
    return -np.sum((z[:,None,:]-model['weights'][None,:,:])**2,axis=2)


def metrics(truth, prediction):
    y=np.array(truth); p=np.array(prediction)
    recall={c:float(np.mean(p[y==c]==c)) if sum(y==c) else None for c in CLASSES}
    ay=y!='other'; ap=p!='other'; tp=int(sum(ay&ap))
    return dict(correct=int(sum(y==p)),total=len(y),accuracy=float(np.mean(y==p)),
                macro_recall=float(np.mean([v for v in recall.values() if v is not None])),recall=recall,
                axel_precision=tp/int(sum(ap)) if sum(ap) else None,
                axel_recall=tp/int(sum(ay)) if sum(ay) else None,
                confusion={c:{d:int(sum((y==c)&(p==d))) for d in CLASSES} for c in CLASSES})


_MODEL = None

def extractor_provenance():
    import torch
    import torchvision
    checkpoint=ROOT/'phase-cache/torch/checkpoints/r3d_18-b3b3357e.pth'
    return dict(extractor=EXTRACTOR,torch=torch.__version__,torchvision=torchvision.__version__,
                checkpoint_sha256=sha(checkpoint) if checkpoint.exists() else None,
                extraction_code_sha256=hashlib.sha256(inspect.getsource(embedding).encode()).hexdigest())

def validate_clip_duration(duration, frame_count=0):
    if duration>60 or frame_count>3600:
        raise ValueError('Input must be a short single-element clip, at most 60 seconds / 3600 frames')

def embedding(video_path, cache_dir=None):
    import torch
    import torchvision
    import imageio_ffmpeg
    global _MODEL
    digest=sha(video_path)
    cache=Path(cache_dir or ROOT/'phase-cache/video-type')
    cache.mkdir(parents=True,exist_ok=True)
    cached=cache/(digest+'.npz')
    if cached.exists():
        with np.load(cached,allow_pickle=False) as item:
            if 'provenance' in item and json.loads(str(item['provenance'])) == extractor_provenance():
                return item['feature'],digest
    reader=imageio_ffmpeg.read_frames(str(video_path),pix_fmt='rgb24',output_params=['-vf','scale=171:128'])
    metadata=next(reader)
    try:
        validate_clip_duration(metadata.get('duration',0))
    except ValueError:
        reader.close()
        raise
    frames=[]
    try:
        for frame in reader:
            validate_clip_duration(0,len(frames)+1)
            frames.append(np.frombuffer(frame,dtype=np.uint8).reshape(128,171,3).copy())
    finally:
        reader.close()
    if not frames:
        raise ValueError('No decoded video frames')
    indices=np.linspace(0,len(frames)-1,16).round().astype(int)
    torch.hub.set_dir(str(ROOT/'phase-cache/torch'))
    if _MODEL is None:
        weights=torchvision.models.video.R3D_18_Weights.KINETICS400_V1
        net=torchvision.models.video.r3d_18(weights=weights)
        net.fc=torch.nn.Identity()
        device='mps' if torch.backends.mps.is_available() else 'cpu'
        torch.set_num_threads(2)
        net.eval().to(device)
        _MODEL=(net,weights.transforms(),device)
    net,transform,device=_MODEL
    clip=torch.from_numpy(np.stack([frames[i] for i in indices])).permute(0,3,1,2)
    with torch.inference_mode():
        feature=net(transform(clip).unsqueeze(0).to(device)).cpu().numpy()[0]
    np.savez_compressed(cached,feature=feature,extractor=EXTRACTOR,source_sha256=digest,
                        frame_indices=indices,decoded_frames=len(frames),
                        provenance=json.dumps(extractor_provenance(),sort_keys=True))
    return feature,digest


def predict_clip(video_path, artifact_path, cache_dir=None):
    with np.load(artifact_path,allow_pickle=False) as a:
        model={k:a[k] for k in ['classes','mean','std','weights','method']}
        if str(a['extractor']) != EXTRACTOR:
            raise ValueError('Artifact extractor mismatch')
        trained_provenance=json.loads(str(a['extractor_provenance']))
    feature,digest=embedding(video_path,cache_dir)
    if trained_provenance != extractor_provenance():
        raise ValueError('Artifact weights, runtime, or extraction code differs from training')
    scores=score_classifier(model,feature[None,:])[0]
    return dict(predicted_label=str(model['classes'][np.argmax(scores)]),
                raw_scores={str(c):float(s) for c,s in zip(model['classes'],scores)},
                classes=model['classes'].tolist(),extraction_status='ok',
                scope='short_single_element_clip',video_sha256=digest,
                limitation='Scores are not calibrated probabilities; no underrotation prediction.')


def train(manifest_path, output):
    manifest_path=Path(manifest_path)
    manifest=json.loads(manifest_path.read_text())
    items=manifest['items']
    if manifest.get('originalSplit') != 'train' or any(i.get('split','train')!='train' for i in items):
        raise ValueError('Only original official train split allowed')
    excluded=[dict(file=i['file'],label=i['label'],reason='No unambiguous single-element target') for i in items if int(i['label']) not in LABEL_MAP]
    items=[i for i in items if int(i['label']) in LABEL_MAP]
    records=[]; features=[]; source_groups={}
    for index,item in enumerate(items):
        path=manifest_path.parent/item['file']
        if sha(path)!=item['sha256']:
            raise ValueError('Video hash mismatch: '+str(path))
        digest=sha(path)
        if digest in source_groups and source_groups[digest] != item['group']:
            raise ValueError('Identical video bytes appear in different evaluation groups')
        source_groups[digest]=item['group']
        feature,digest=embedding(path)
        records.append(dict(file=item['file'],sha256=digest,group=item['group'],
                            truth=LABEL_MAP[int(item['label'])]))
        features.append(feature)
        print(json.dumps({'extracted':index+1,'total':len(items)}),flush=True)
    x=np.stack(features); y=np.array([r['truth'] for r in records]); groups=[r['group'] for r in records]
    folds=grouped_folds(groups)
    majority=np.empty(len(y),dtype=object)
    for tr,te in folds:
        labels,counts=np.unique(y[tr],return_counts=True)
        majority[te]=labels[np.argmax(counts)]
    variants={'majority':dict(metrics=metrics(y,majority),predictions=majority.tolist())}
    for method in ['ridge','centroid']:
        prediction=np.empty(len(y),dtype=object)
        for tr,te in folds:
            model=fit_classifier(x[tr],y[tr],method)
            prediction[te]=model['classes'][score_classifier(model,x[te]).argmax(axis=1)]
        variants[method]=dict(metrics=metrics(y,prediction),predictions=prediction.tolist())
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    result=dict(method='Fixed class-balanced ridge alpha10 primary; centroid comparison only.',
                scope='Official train grouped CV only; prefix groups not verified athlete identity.',
                extractor=EXTRACTOR,manifest_sha256=sha(manifest_path),records=records,variants=variants,
                extractor_provenance=extractor_provenance(),excluded=excluded,
                class_counts={c:int(sum(y==c)) for c in CLASSES},
                folds=[dict(train=tr.tolist(),test=te.tolist()) for tr,te in folds])
    (output/'results.json').write_text(json.dumps(result,indent=2))
    final=fit_classifier(x,y,'ridge')
    np.savez_compressed(output/'classifier.npz',**final,extractor=EXTRACTOR,
                        manifest_sha256=sha(manifest_path),provenance=json.dumps(result),
                        extractor_provenance=json.dumps(extractor_provenance(),sort_keys=True))
    print(json.dumps({k:v['metrics'] for k,v in variants.items()},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    sub=parser.add_subparsers(dest='command',required=True)
    t=sub.add_parser('train');t.add_argument('manifest');t.add_argument('--output',default=str(ROOT/'work/video-type-pilot-v1'))
    p=sub.add_parser('predict');p.add_argument('video');p.add_argument('artifact')
    args=parser.parse_args()
    if args.command=='train':train(args.manifest,args.output)
    else:print(json.dumps(predict_clip(args.video,args.artifact),indent=2))
