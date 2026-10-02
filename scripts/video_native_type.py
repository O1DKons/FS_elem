"""Predeclared native-time pose experiment. No automatic extraction or training."""
import argparse
import hashlib
import inspect
import json
from pathlib import Path
import numpy as np
from video_type_model import ROOT,CLASSES,LABEL_MAP,sha,grouped_folds,fit_classifier,score_classifier
from video_pose_type import evaluate

FREQUENCIES=np.arange(.5,12.01,.5)
PAIRS=((5,6),(11,12),(9,10),(15,16))
PAIR_NAMES=('shoulders','hips','wrists','ankles')
CACHE=ROOT/'phase-cache/video-pose-dense-v2'
OUTPUT=ROOT/'work/video-native-type-v1'


def interpolated_psd(values,fps):
    """One-sided Hann periodogram density on a fixed physical-frequency grid."""
    window=np.hanning(len(values))
    centered=values-np.mean(values)
    transformed=np.fft.rfft(centered*window)
    density=np.abs(transformed)**2/(fps*np.sum(window**2))
    if len(values)%2==0:density[1:-1]*=2
    else:density[1:]*=2
    frequencies=np.fft.rfftfreq(len(values),d=1/fps)
    return np.interp(FREQUENCIES,frequencies,density)


def native_features(points,scores,fps,frame_indices=None):
    p=np.asarray(points,float);s=np.asarray(scores,float)
    if p.ndim!=3 or p.shape[1:]!=(17,2) or s.shape!=p.shape[:2]:raise ValueError('Expected native COCO17 arrays')
    n=len(p);indices=np.arange(n) if frame_indices is None else np.asarray(frame_indices)
    if indices.shape!=(n,):raise ValueError('Frame index shape mismatch')
    details=dict(frames=n,unique_source_indices=int(len(np.unique(indices))),fps=float(fps),valid_counts=[],reason=None)
    if n<8 or len(np.unique(indices))<8:
        details['reason']='insufficient_distinct_frames';return None,details
    if not np.isfinite(fps) or fps<=0:raise ValueError('Invalid native FPS')
    if fps/2<FREQUENCIES[-1]:
        details['reason']='frequency_grid_above_nyquist';return None,details
    torso=np.linalg.norm(p[:,5:7].mean(axis=1)-p[:,11:13].mean(axis=1),axis=1)
    torso_ok=(s[:,[5,6,11,12]]>=.3).all(axis=1)&np.isfinite(torso)&(torso>=2)
    features=[];failed=False
    for kind in ('signed_dx','distance'):
        for a,b in PAIRS:
            delta=p[:,a]-p[:,b]
            raw=delta[:,0] if kind=='signed_dx' else np.linalg.norm(delta,axis=1)
            valid=torso_ok&(s[:,a]>=.3)&(s[:,b]>=.3)&np.isfinite(raw)
            count=int(sum(valid));distinct=int(len(np.unique(indices[valid])))
            details['valid_counts'].append(count)
            if count/n<.75 or distinct<8:
                failed=True;continue
            observed=raw[valid]/torso[valid]
            # Only within-clip gaps are filled; endpoints use nearest observed value.
            filled=np.interp(np.arange(n),np.flatnonzero(valid),observed)
            features.extend([float(np.mean(observed)),float(np.std(observed))])
            features.extend(interpolated_psd(filled,float(fps)))
    if failed:
        details['reason']='insufficient_confident_samples';return None,details
    result=np.asarray(features,float)
    if result.shape!=(208,) or not np.isfinite(result).all():raise ValueError('Invalid native feature vector')
    return result,details


def feature_contract():
    specification=dict(numpy_version=np.__version__,channels=[name+'.'+kind for kind in ('signed_dx','distance') for name in PAIR_NAMES],
                       frequency_hz=FREQUENCIES.tolist(),confidence=.3,minimum_coverage=.75,minimum_distinct_valid_frames=8,
                       minimum_torso_pixels=2,window='Hann',psd='one-sided density; linear interpolation in Hz',
                       gaps='within-clip linear interpolation; nearest observed endpoint extension',
                       scalar_statistics='mean/std of confident observed samples',features_include_fps_or_duration=False)
    code=inspect.getsource(native_features)+inspect.getsource(interpolated_psd)+json.dumps(specification,sort_keys=True)
    return dict(**specification,code_sha256=hashlib.sha256(code.encode()).hexdigest())


def pilot_items(manifest):
    data=json.loads(Path(manifest).read_text())
    if data.get('originalSplit')!='train':raise ValueError('Only original official train is permitted')
    if any(i.get('split','train')!='train' for i in data['items']):raise ValueError('Mixed split is forbidden')
    items=[i for i in data['items'] if int(i['label']) in LABEL_MAP]
    if len(items)!=190:raise ValueError('Expected unchanged190-clip development pilot')
    baseline=json.loads((ROOT/'work/video-type-pilot-v1/results.json').read_text())
    if [i['sha256'] for i in items]!=[r['sha256'] for r in baseline['records']]:raise ValueError('Pilot ordering/source changed')
    return items,baseline


def require_complete(items,cache):
    missing=[i['sha256'] for i in items if not (Path(cache)/(i['sha256']+'.npz')).is_file()]
    if missing:raise ValueError(f'Native extraction incomplete: {len(items)-len(missing)}/{len(items)} caches. Training is not allowed.')


def validated_native(item,cache):
    from extract_dense_pose_type import extract
    path=Path(cache)/(item['sha256']+'.npz')
    with np.load(path,allow_pickle=False) as d:
        provenance=json.loads(str(d['provenance']))
        expected=hashlib.sha256(inspect.getsource(extract).encode()).hexdigest()
        if str(d['source_sha256'])!=item['sha256'] or provenance.get('native_extraction_sha256')!=expected:
            raise ValueError('Native v2 source/extraction provenance mismatch')
        if provenance.get('sampling')!='every decoded source frame; nominal FPS timestamps; no uniform32 reduction':
            raise ValueError('Wrong native sampling contract')
        points=d['points'];scores=d['scores'];indices=d['frame_indices'];times=d['times'];fps=float(d['fps'])
        if points.ndim!=3 or points.shape[1:]!=(17,2) or scores.shape!=points.shape[:2]:raise ValueError('Native point shape mismatch')
        if not np.isfinite(fps) or fps<=0:raise ValueError('Invalid native cache FPS')
        if not np.array_equal(indices,np.arange(len(points))) or not np.allclose(times,np.arange(len(points))/fps,rtol=0,atol=1e-10):
            raise ValueError('Native frame/timestamp contract mismatch')
    return points,scores,fps,indices,provenance,sha(path)


def train(manifest,cache=CACHE,output=OUTPUT):
    items,baseline=pilot_items(manifest)
    require_complete(items,cache)  # No partial-data training, even when most caches exist.
    inputs=[];shared_provenance=None
    for item in items:
        video=Path(manifest).parent/item['file']
        if sha(video)!=item['sha256']:raise ValueError('Pilot video source changed')
        native=validated_native(item,cache)
        if shared_provenance is None:shared_provenance=native[4]
        elif native[4]!=shared_provenance:raise ValueError('Mixed native extractor/weight/runtime provenance')
        inputs.append(native)
    contract=feature_contract();records=[];features=[]
    feature_cache=ROOT/'phase-cache/video-native-type-v1';feature_cache.mkdir(parents=True,exist_ok=True)
    for item,native in zip(items,inputs):
        points,scores,fps,indices,provenance,cache_sha=native
        feature,details=native_features(points,scores,fps,indices)
        vector=feature if feature is not None else np.full(208,np.nan)
        cache_path=feature_cache/(item['sha256']+'-'+contract['code_sha256'][:12]+'.npz')
        np.savez_compressed(cache_path,feature=vector,valid=feature is not None,details=json.dumps(details),
                            source_sha256=item['sha256'],native_cache_sha256=cache_sha,contract=json.dumps(contract))
        records.append(dict(file=item['file'],sha256=item['sha256'],group=item['group'],truth=LABEL_MAP[int(item['label'])],
                            valid=feature is not None,details=details,native_cache_sha256=cache_sha,feature_cache=str(cache_path),
                            feature_cache_sha256=sha(cache_path)))
        features.append(vector)
    x=np.stack(features);y=np.array([r['truth'] for r in records]);valid=np.array([r['valid'] for r in records])
    folds=grouped_folds([r['group'] for r in records])
    fold_records=[dict(train=tr.tolist(),test=te.tolist()) for tr,te in folds]
    if fold_records!=baseline['folds']:raise ValueError('Development folds changed')
    prediction=np.full(len(y),'abstain',dtype=object)
    for tr,te in folds:
        tr=tr[valid[tr]];te=te[valid[te]]
        if not len(tr) or not len(te):continue
        model=fit_classifier(x[tr],y[tr],'ridge')
        prediction[te]=model['classes'][score_classifier(model,x[te]).argmax(axis=1)]
    result=dict(scope='PREDECLARED native-time pose-only DEVELOPMENT evaluation; unverified prefix groups; not underrotation or independent accuracy.',
                method='Class-balanced ridge alpha10, unchanged helper; no comparison variants.',contract=contract,
                records=records,predictions=prediction.tolist(),metrics=evaluate(y,prediction),folds=fold_records,
                manifest_sha256=sha(manifest),native_provenance=shared_provenance,
                classifier_code_sha256=hashlib.sha256((inspect.getsource(fit_classifier)+inspect.getsource(score_classifier)).encode()).hexdigest())
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    (output/'results.json').write_text(json.dumps(result,indent=2))
    if any(valid):
        np.savez_compressed(output/'classifier.npz',**fit_classifier(x[valid],y[valid],'ridge'),provenance=json.dumps(result))
    print(json.dumps(result['metrics'],indent=2))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['check','train'])
    parser.add_argument('--manifest',type=Path,default=ROOT/'data/skatingverse-pilot-v1/manifest.json')
    parser.add_argument('--cache',type=Path,default=CACHE);parser.add_argument('--output',type=Path,default=OUTPUT)
    args=parser.parse_args()
    if args.command=='check':
        items,_=pilot_items(args.manifest);available=sum((args.cache/(i['sha256']+'.npz')).is_file() for i in items)
        print(json.dumps(dict(available=available,required=len(items),all_files_present=available==len(items),training_started=False)))
    else:train(args.manifest,args.cache,args.output)


if __name__=='__main__':main()
