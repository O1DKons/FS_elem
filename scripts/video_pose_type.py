"""Fixed motion-centric pose descriptor pilot; no clean/short prediction."""
import argparse
import importlib.metadata
import inspect
import json
from pathlib import Path
import numpy as np
from video_type_model import ROOT, LABEL_MAP, CLASSES, sha, grouped_folds, fit_classifier, score_classifier


def temporal_features(points,scores):
    points=np.asarray(points,float); scores=np.asarray(scores,float)
    torso=np.linalg.norm(points[:,5:7].mean(axis=1)-points[:,11:13].mean(axis=1),axis=1)
    torso_ok=(scores[:,[5,6,11,12]]>=.3).all(axis=1)&(torso>=2)&np.isfinite(torso)
    channels=[];coverage=[]
    for a,b in [(5,6),(11,12),(9,10),(15,16)]:
        distances=np.linalg.norm(points[:,a]-points[:,b],axis=1)
        valid=torso_ok&(scores[:,a]>=.3)&(scores[:,b]>=.3)&np.isfinite(distances)
        coverage.append(int(sum(valid)))
        if sum(valid)<24:
            channels.append(None);continue
        values=distances[valid]/torso[valid]
        filled=np.interp(np.arange(32),np.flatnonzero(valid),values)
        spectrum=np.abs(np.fft.rfft(filled-filled.mean()))[1:9]/32
        channels.append(np.r_[values.mean(),values.std(),spectrum])
    if any(c is None for c in channels):return None,coverage
    return np.concatenate(channels),coverage


_BODY=None
_PROVENANCE=None

def model_and_provenance():
    global _BODY,_PROVENANCE
    if _BODY is None:
        from rtmlib import Body
        import contextlib, sys
        with contextlib.redirect_stdout(sys.stderr):
            _BODY=Body(mode='balanced',to_openpose=False,backend='onnxruntime',device='cpu')
        _PROVENANCE=dict(detector_sha256=sha(_BODY.det_model.onnx_model),pose_sha256=sha(_BODY.pose_model.onnx_model),
                         packages={name:importlib.metadata.version(name) for name in ['rtmlib','onnxruntime','numpy','opencv-python']},
                         extraction_code_sha256=__import__('hashlib').sha256(inspect.getsource(extract_pose).encode()).hexdigest(),
                         settings='32uniform;detectevery4;firstlargestthennearestcenter;poseboxpad25%;confidence0.3')
    return _BODY,_PROVENANCE


def extract_pose(video,cache_dir=None):
    import cv2
    body,provenance=model_and_provenance()
    digest=sha(video);cache=Path(cache_dir or ROOT/'phase-cache/video-pose-type')
    cache.mkdir(parents=True,exist_ok=True);path=cache/(digest+'.npz')
    if path.exists():
        with np.load(path,allow_pickle=False) as item:
            if json.loads(str(item['provenance']))==provenance:
                return item['points'],item['scores'],dict(source_sha256=digest,cache=str(path),provenance=provenance)
    cap=cv2.VideoCapture(str(video));count=int(cap.get(cv2.CAP_PROP_FRAME_COUNT));fps=cap.get(cv2.CAP_PROP_FPS)
    if count<1 or fps<=0 or count/fps>60:
        cap.release();raise ValueError('Invalid video or longer than60seconds')
    indices=np.linspace(0,count-1,32).round().astype(int)
    points=np.full((32,17,2),np.nan);scores=np.zeros((32,17));box=None;boxes=[]
    try:
        for t,index in enumerate(indices):
            cap.set(cv2.CAP_PROP_POS_FRAMES,int(index));ok,image=cap.read()
            if not ok:boxes.append(None);continue
            h,w=image.shape[:2]
            if t%4==0 or box is None:
                detections=[np.asarray(b[:4],float) for b in body.det_model(image) if len(b)>=4 and b[2]>b[0] and b[3]>b[1]]
                if detections:
                    if box is None:box=max(detections,key=lambda b:(b[2]-b[0])*(b[3]-b[1]))
                    else:
                        center=(box[:2]+box[2:])/2
                        box=min(detections,key=lambda b:np.linalg.norm((b[:2]+b[2:])/2-center))
                else:box=None
            boxes.append(box.tolist() if box is not None else None)
            if box is None:continue
            p,s=body.pose_model(image,bboxes=[box.tolist()]);points[t]=p[0,:17];scores[t]=s[0,:17]
            valid=(scores[t]>=.3)&np.isfinite(points[t]).all(axis=1)
            if sum(valid)>=8:
                low=points[t,valid].min(axis=0);high=points[t,valid].max(axis=0)
                padding=np.maximum((high-low)*.25,10)
                box=np.r_[np.maximum(low-padding,0),np.minimum(high+padding,[w-1,h-1])]
    finally:cap.release()
    np.savez_compressed(path,points=points,scores=scores,frame_indices=indices,
                        boxes=json.dumps(boxes),provenance=json.dumps(provenance),source_sha256=digest)
    return points,scores,dict(source_sha256=digest,cache=str(path),provenance=provenance)


def evaluate(truth,prediction):
    y=np.array(truth);p=np.array(prediction);answered=p!='abstain'
    recall={c:float(np.mean(p[y==c]==c)) if sum(y==c) else None for c in CLASSES}
    axel=np.isin(p,['1A','2A','3A']);true_axel=y!='other';tp=int(sum(axel&true_axel))
    return dict(correct=int(sum(y==p)),total=len(y),accuracy=float(np.mean(y==p)),
                coverage=float(np.mean(answered)),answered=int(sum(answered)),
                macro_recall=float(np.mean([v for v in recall.values() if v is not None])),recall=recall,
                axel_precision=tp/int(sum(axel)) if sum(axel) else None,
                axel_recall=tp/int(sum(true_axel)),
                confusion={c:{d:int(sum((y==c)&(p==d))) for d in CLASSES+['abstain']} for c in CLASSES})


def train(manifest,output):
    manifest=Path(manifest);data=json.loads(manifest.read_text());items=data['items']
    if data.get('originalSplit')!='train':raise ValueError('Official train only')
    items=[i for i in items if int(i['label']) in LABEL_MAP]
    records=[];features=[]
    for index,item in enumerate(items):
        video=manifest.parent/item['file']
        if sha(video)!=item['sha256']:raise ValueError('Source hash mismatch')
        try:
            p,s,provenance=extract_pose(video)
            feature,coverage=temporal_features(p,s);error=None
        except (ValueError,RuntimeError) as exc:
            feature=None;coverage=[];error=str(exc)
        records.append(dict(file=item['file'],group=item['group'],sha256=item['sha256'],truth=LABEL_MAP[int(item['label'])],
                            valid=feature is not None,coverage=coverage,error=error))
        features.append(feature if feature is not None else np.zeros(40))
        print(json.dumps(dict(extracted=index+1,total=len(items),valid=feature is not None)),flush=True)
    x=np.stack(features);y=np.array([r['truth'] for r in records]);valid=np.array([r['valid'] for r in records])
    folds=grouped_folds([r['group'] for r in records]);variants={}
    for method in ['ridge','centroid']:
        prediction=np.full(len(y),'abstain',dtype=object)
        for tr,te in folds:
            train_indices=tr[valid[tr]];test_indices=te[valid[te]]
            if not len(train_indices) or not len(test_indices):continue
            model=fit_classifier(x[train_indices],y[train_indices],method)
            prediction[test_indices]=model['classes'][score_classifier(model,x[test_indices]).argmax(axis=1)]
        variants[method]=dict(metrics=evaluate(y,prediction),predictions=prediction.tolist())
    _,provenance=model_and_provenance()
    feature_hash=__import__('hashlib').sha256(inspect.getsource(temporal_features).encode()).hexdigest()
    result=dict(method='Fixed ridge alpha10 primary; centroid comparison. Same190/folds as generic video.',
                records=records,variants=variants,manifest_sha256=sha(manifest),provenance=provenance,feature_code_sha256=feature_hash,
                folds=[dict(train=tr.tolist(),test=te.tolist()) for tr,te in folds])
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    (output/'results.json').write_text(json.dumps(result,indent=2))
    if any(valid):
        np.savez_compressed(output/'classifier.npz',**fit_classifier(x[valid],y[valid],'ridge'),
                            provenance=json.dumps(result),feature_code_sha256=feature_hash)
    print(json.dumps({k:v['metrics'] for k,v in variants.items()},indent=2))


def predict_clip(video_path,artifact_path,cache_dir=None):
    with np.load(artifact_path,allow_pickle=False) as a:
        model={k:a[k] for k in ['classes','mean','std','weights','method']}
        trained=json.loads(str(a['provenance']))
        feature_hash=str(a['feature_code_sha256'])
    p,s,meta=extract_pose(video_path,cache_dir)
    if meta['provenance']!=trained['provenance'] or feature_hash!=__import__('hashlib').sha256(inspect.getsource(temporal_features).encode()).hexdigest():
        raise ValueError('Pose extractor or feature provenance mismatch')
    feature,coverage=temporal_features(p,s)
    result=dict(predicted_label='abstain',raw_scores={},classes=model['classes'].tolist(),
                extraction_status='insufficient_pose',scope='short_single_element_clip',
                video_sha256=meta['source_sha256'],pose_coverage=coverage,
                limitation='Nominal class only; no measured rotation or clean/short prediction.')
    if feature is not None:
        scores=score_classifier(model,feature[None,:])[0]
        result.update(predicted_label=str(model['classes'][np.argmax(scores)]),extraction_status='ok',
                      raw_scores={str(c):float(v) for c,v in zip(model['classes'],scores)})
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('manifest',nargs='?');p.add_argument('--output',default=str(ROOT/'work/video-pose-type-v1'))
    p.add_argument('--predict');p.add_argument('--artifact',default=str(ROOT/'work/video-pose-type-v1/classifier.npz'))
    a=p.parse_args()
    if a.predict:print(json.dumps(predict_clip(a.predict,a.artifact),indent=2))
    elif a.manifest:train(a.manifest,a.output)
    else:p.error('Provide a training manifest or --predict VIDEO')
