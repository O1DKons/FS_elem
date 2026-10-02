"""Consolidated frozen baseline: native flight/family -> compatible RTMW nominal.

No training or expert annotations are read by this entry point. Research baseline
quality remains unconfirmed; training/source overlap is recorded explicitly.
"""
import argparse
import json
import subprocess
import tempfile
import time
from pathlib import Path
import joblib
import numpy as np
from pose_cache_contract import sha
from axel_features import feature_contract
from axel_baseline_inference import infer_family
from axel_nominal import nominal_prediction
from axel_rtmw_windows import window_specs, validate_window
ROOT=Path(__file__).resolve().parents[1]


def checked_json(entry):
    path=ROOT/entry['path']
    if sha(path)!=entry['sha256']:raise ValueError('Artifact hash mismatch: '+entry['path'])
    return json.loads(path.read_text())


def verify_nominal_contract(config,training):
    expected=training['models']['nominal'].get('trainingPoseSha256')
    if not expected or config['nominalPoseContract'].get('pose_sha256')!=expected:
        raise ValueError('Nominal pose config incompatible with recorded training weights')


def main():
    p=argparse.ArgumentParser()
    p.add_argument('video',type=Path)
    p.add_argument('--config',type=Path,default=ROOT/'configs/axel-baseline-v1.json')
    p.add_argument('--cache',type=Path,default=ROOT/'phase-cache/full-program-native-runtime-v1')
    p.add_argument('--nominal-cache',type=Path,default=ROOT/'phase-cache/axel-rtmw-windows-v1')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--pose-python',type=Path,default=ROOT/'work/step23-rtmpose/venv/bin/python')
    p.add_argument('--athlete',help='Recorded athlete label; does not establish cross-collection identity')
    a=p.parse_args()
    if a.output.exists():raise ValueError('Output already exists; preserve prior results')
    started=time.perf_counter();config_hash=sha(a.config);config=json.loads(a.config.read_text())
    if config['schemaVersion']!=2:raise ValueError('Unsupported baseline configuration')
    if config['featureContract']!=json.loads(json.dumps(feature_contract())):raise ValueError('Feature version mismatch')
    models={entry['role']:entry for entry in config['models']}
    if len(models)!=4 or set(models)!={'flightContext','flightFull','family','nominal'}:raise ValueError('Invalid model roles')
    for entry in models.values():
        if sha(ROOT/entry['path'])!=entry['sha256']:raise ValueError('Model hash mismatch: '+entry['path'])
    training=checked_json(config['trainingManifest'])
    verify_nominal_contract(config,training)
    for role,entry in models.items():
        if training['models'][role]['modelSha256']!=entry['sha256']:raise ValueError('Training manifest/model mismatch')
    for entry in [config['extractor'],config['rtmwExtractor']]:
        if sha(ROOT/entry['path'])!=entry['sha256']:raise ValueError('Extractor hash mismatch')
    source=sha(a.video);cache=a.cache/(source+'.npz');hit=cache.exists();timing={}
    mark=time.perf_counter()
    if not hit:
        subprocess.run([str(a.pose_python),str(ROOT/config['extractor']['path']),str(a.video.resolve()),str(a.cache.resolve())],check=True)
    timing['nativeExtractionSeconds']=time.perf_counter()-mark;mark=time.perf_counter()
    with tempfile.TemporaryDirectory(prefix='axel-validation-') as temp:
        receipt=Path(temp)/'receipt.json'
        code="import sys,json;from pathlib import Path;sys.path.insert(0,sys.argv[1]);from pose_cache_contract import validate_pose_cache;c=json.loads(Path(sys.argv[4]).read_text());r=validate_pose_cache(Path(sys.argv[2]),Path(sys.argv[3]),c['nativePoseContract']);Path(sys.argv[5]).write_text(json.dumps(r))"
        subprocess.run([str(a.pose_python),'-c',code,str(ROOT/'scripts'),str(a.video.resolve()),str(cache.resolve()),str(a.config.resolve()),str(receipt)],check=True)
        validation=json.loads(receipt.read_text())
    timing['validationSeconds']=time.perf_counter()-mark;mark=time.perf_counter()
    flight=[joblib.load(ROOT/models[role]['path']) for role in ['flightContext','flightFull']]
    with np.load(ROOT/models['family']['path'],allow_pickle=False) as d:family=dict(d)
    nominal=joblib.load(ROOT/models['nominal']['path'])
    timing['modelLoadSeconds']=time.perf_counter()-mark;mark=time.perf_counter()
    with np.load(cache,allow_pickle=False) as d:events=infer_family(d['points'],d['scores'],float(d['fps']),d['frame_indices'],flight,family)
    timing['flightFamilySeconds']=time.perf_counter()-mark;mark=time.perf_counter()
    windows=window_specs(events,validation['fps'],validation['frameCount']);entries=[]
    if windows:
        with tempfile.TemporaryDirectory(prefix='axel-nominal-') as temp:
            request=Path(temp)/'request.json';receipt=Path(temp)/'receipt.json'
            request.write_text(json.dumps({'sourceSha256':source,'fps':validation['fps'],'frameCount':validation['frameCount'],'windows':windows}))
            subprocess.run([str(a.pose_python),str(ROOT/config['rtmwExtractor']['path']),str(a.video.resolve()),str(request),str(a.config.resolve()),str(a.nominal_cache.resolve()),str(receipt)],check=True)
            entries=json.loads(receipt.read_text())['entries']
        if [e['eventIndex'] for e in entries]!=[w['eventIndex'] for w in windows]:raise ValueError('Nominal receipt/window mismatch')
    timing['rtmwExtractionSeconds']=time.perf_counter()-mark;mark=time.perf_counter()
    for window,entry in zip(windows,entries):
        path=Path(entry['path'])
        if sha(path)!=entry['sha256']:raise ValueError('RTMW cache changed')
        doc=validate_window(json.loads(path.read_text()),source,validation['fps'],validation['frameCount'],window,config['nominalPoseContract'])
        pred=nominal_prediction(doc,window['startFrame'],window['endFrame'],nominal,doc['provenance'],config['nominalPoseContract'])
        event=events[window['eventIndex']];event['nominal']=pred['nominal'];event['nominalReason']=pred['reason'];event['nominalQuality']=pred['quality'];event['nominalPoseSha256']=entry['sha256']
    timing['nominalInferenceSeconds']=time.perf_counter()-mark
    if sha(a.video)!=source or sha(cache)!=validation['cacheSha256'] or sha(a.config)!=config_hash:raise ValueError('Inputs changed during inference')
    overlap={}
    for role,row in training['models'].items():
        sources=row['trainingSources'];names={r['athleteLabel'] for r in sources}
        overlap[role]={'exactSourceSeen':source in {r['sourceSha256'] for r in sources},'athleteLabelSeen':a.athlete in names if a.athlete else None,'crossCollectionAthleteIdentityVerified':False}
    timing['totalBeforeWriteSeconds']=time.perf_counter()-started
    result={'sourceSha256':source,'configSha256':config_hash,'models':config['models'],'validation':validation,'nativeCacheHit':hit,
            'nominalCaches':entries,'timings':timing,'events':events,'trainingOverlap':overlap,
            'sourceSeenInTraining':any(r['exactSourceSeen'] for r in overlap.values()),'athleteSeenInTraining':None,
            'goal70Verified':False,'limitations':['Frozen research baseline; family errors retained','Nominal supports only1A/2A, not continuous physical turns','Cross-collection athlete/original-recording identities not reconciled','Cached replay timing is not cold inference speed','Underrotation unassessed']}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x') as stream:json.dump(result,stream,ensure_ascii=False,indent=2)
    print(json.dumps({'output':str(a.output),'events':events,'timings':timing,'sourceSeenInTraining':result['sourceSeenInTraining']},ensure_ascii=False))
if __name__=='__main__':main()
