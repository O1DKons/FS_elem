"""Fixed RTMW/actual-PTS research recipe for one original video; no fit/truth input."""
import os
os.environ['OMP_NUM_THREADS']='2'
os.environ['OPENBLAS_NUM_THREADS']='2'
import argparse
import importlib.util
import importlib.metadata
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from support import ROOT, SCRIPTS, asset_path, progress, run_child, validate_cache_directory
import joblib
import numpy as np

from pose_cache_contract import sha
from sparse_pose_timestamps import pose_arrays_pts,timestamps_sha256
from axel_family import segment_features
from run_rotation_proxy_baseline import transform
from video_type_model import score_classifier
from pose_models import ort_threads,validate_runtime_sessions




def read(path):return json.loads(Path(path).read_text())


def write_new(path,value):
    with Path(path).open('x') as stream:json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False)


def executable_path(path):
    # Resolving a venv's python symlink loses its pyvenv.cfg environment.
    return Path(path).absolute()


def validate_cache_manifest(receipt,source_sha,recipe_sha):
    files=receipt.get('filesSha256')
    if (receipt.get('sourceSha256')!=source_sha or receipt.get('recipeSha256')!=recipe_sha
            or not isinstance(files,dict)
            or set(files)!={'timeline.json','sparse.json','dense-request.json','dense.json'}
            or any(not isinstance(h,str) or not re.fullmatch('[0-9a-f]{64}',h) for h in files.values())):
        raise ValueError('Cache needs the exact four bound artifact hashes and source/recipe identity')


def nominal_usable(quality):
    return quality['usableTorsoFrames']>=3 and quality['finiteSpectralFeatures']>0


def validate_dense(document,record,windows,recipe):
    if 'ortThreads' in recipe:validate_runtime_sessions(document.get('runtimeSessions'),recipe,required=bool(windows))
    if (type(document.get('schemaVersion')) is not int or document['schemaVersion']!=1
            or document.get('extractorSha256')!=recipe['inputSha256'][recipe['worker']]
            or document.get('geometry')!=dict(recipe['denseGeometry'],width=record['width'],height=record['height'])):
        raise ValueError('Dense producer/schema/coordinate layout differs')
    if any(document.get(k)!=record[k] for k in ['sourceSha256','fps','frameCount']):
        raise ValueError('Dense source identity/metadata differs')
    if any(document.get(k)!=recipe[k] for k in ['poseSha256','detectorSha256']):
        raise ValueError('Dense pose/detector identity differs')
    items=document.get('items',[])
    if [i.get('window') for i in items]!=windows:
        raise ValueError('Dense automatic windows differ')
    for item,window in zip(items,windows):
        indices=range(window['cropStartFrame'],window['cropEndFrame']+1)
        if set(item['frames'])!={str(n) for n in indices}:
            raise ValueError('Dense source-frame coverage incomplete')
        for n in indices:
            row=item['frames'][str(n)]
            if (type(row.get('frameIndex')) is not int or row['frameIndex']!=n
                    or type(row.get('time')) not in (int,float) or not np.isfinite(row['time'])
                    or abs(row['time']-record['timestampsSeconds'][n])>1e-6):
                raise ValueError('Dense source indices/PTS differ')
            p,s=np.asarray(row['points'],float),np.asarray(row['scores'],float)
            if p.size or s.size:
                if p.shape!=(23,2) or s.shape!=(23,) or not np.isfinite(p).all() or not np.isfinite(s).all():
                    raise ValueError('Malformed dense RTMW23 observations')
    return items


def helper(path,name,config):
    spec=importlib.util.spec_from_file_location(name,asset_path(config,path))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def check_recipe(recipe,config):
    ort_threads(recipe)
    if recipe.get('schemaVersion')!=1 or recipe.get('mode') not in ('fixed_single_development_recipe','fixed_release_recipe'):
        raise ValueError('Unsupported research recipe')
    for package,version in recipe['scienceVersions'].items():
        if importlib.metadata.version(package)!=version:raise ValueError('Science environment differs: '+package)
    for path,digest in recipe['inputSha256'].items():
        if sha(asset_path(config,path))!=digest:raise ValueError('Pinned recipe input changed: '+path)
    if set(recipe['models'])!={'flight','family','nominal'}:
        raise ValueError('Expected exactly flight/family/nominal roles')
    for row in recipe['models'].values():
        if sha(asset_path(config,row['path']))!=row['sha256']:raise ValueError('Pinned model changed')


def run(video,config,cache_root,pose_python):
    started=time.perf_counter();recipe=read(config);check_recipe(recipe,config);recipe_sha=sha(config)
    source_sha=sha(video);directory=cache_root/recipe_sha/source_sha
    directory.mkdir(parents=True,exist_ok=True)
    timing={};mark=time.perf_counter()
    worker=asset_path(config,recipe['worker']);progress('probe');cache_receipt=directory/'cache-manifest.json';cache_hit=cache_receipt.exists()
    validate_cache_directory(directory,cache_hit)
    with tempfile.TemporaryDirectory(prefix='axel-pts-probe-') as temporary:
        probe_path=Path(temporary)/'timeline.json'
        run_child([str(pose_python),str(worker),'probe','--video',str(video),
            '--config',str(config),'--output',str(probe_path)],directory/f'probe-{time.time_ns()}.log')
        record=read(probe_path)
    timing['fullSourceProbeSeconds']=time.perf_counter()-mark
    if cache_hit:
        receipt=read(cache_receipt)
        validate_cache_manifest(receipt,source_sha,recipe_sha)
        for name,digest in receipt['filesSha256'].items():
            if sha(directory/name)!=digest:raise ValueError('Cache artifact changed: '+name)
        if read(directory/'timeline.json')!=record:raise ValueError('Cached timeline differs from complete source decode')
    else:
        write_new(directory/'timeline.json',record)
    mark=time.perf_counter()
    progress('sparse',0,record['frameCount'])
    if not cache_hit:
        run_child([str(pose_python),str(asset_path(config,recipe['sparseExtractor'])),
            '--video',str(video),'--output',str(directory/'sparse.json'),'--config',str(config),
            '--sample-fps',str(recipe['sampleFps'])],directory/'sparse-extraction.log')
    progress('sparse',record['frameCount'],record['frameCount'])
    timing['sparseExtractionSeconds']=time.perf_counter()-mark;mark=time.perf_counter()
    expected={k:record[k] for k in ['sourceSha256','fps','frameCount','width','height']}
    expected.update(poseSha256=recipe['poseSha256'],detectorSha256=recipe['detectorSha256'],
        requestedFps=recipe['sampleFps'],stepSourceFrames=max(1,round(record['fps']/recipe['sampleFps'])),
        timestampsSha256=timestamps_sha256(record['timestampsSeconds']))
    sparse_document=read(directory/'sparse.json')
    if 'ortThreads' in recipe:validate_runtime_sessions(sparse_document.get('runtimeSessions'),recipe)
    raw,usable,indices,times=pose_arrays_pts(sparse_document,record,expected)
    context=helper(recipe['helpers']['temporal'],'research_temporal',config)
    decoder=helper(recipe['helpers']['decoder'],'research_decoder',config)
    windows_api=helper(recipe['helpers']['windows'],'research_windows',config)
    models={}
    for role,row in recipe['models'].items():
        model=joblib.load(asset_path(config,row['path']))
        if model.get('protocolSha256')!=row['protocolSha256']:raise ValueError('Model producer protocol differs')
        models[role]=model
    if set(models['nominal']['model']['classes'].tolist())!={'1A','2A'}:
        raise ValueError('Nominal model does not implement1A/2A')
    progress('flight_family',0,record['frameCount'])
    probabilities=np.full(len(times),np.nan)
    if usable.any():
        flight=models['flight'];x=context.context_features(raw,times,usable)
        probabilities[usable]=flight['model'].predict_proba(transform(x[usable],flight['state']))[:,1]
    intervals=decoder.decode(times,probabilities,usable,record['duration'],recipe['flightThreshold'])
    rows,windows=[],[]
    for index,interval in enumerate(intervals):
        family=models['family'];x=segment_features(raw,times,usable,interval['start'],interval['end'])
        scores=score_classifier(family['model'],transform(x[None],family['state']))[0]
        if not np.isfinite(scores).all():raise ValueError('Nonfinite family inference')
        label=str(family['model']['classes'][scores.argmax()]);cid=source_sha[:16]+f'-candidate-{index+1:02d}'
        rows.append(dict(id=cid,start=interval['start'],end=interval['end'],family=label,
            nominal=None,nominalReason='not_an_axel' if label!='axel' else 'not_yet_assessed',
            familyScoresUncalibrated=dict(zip(family['model']['classes'].tolist(),scores.tolist())),underrotation=None))
        if label=='axel':windows.append(dict(windows_api.dense_window(record['timestampsSeconds'],interval['start'],interval['end']),candidateId=cid))
    progress('flight_family',record['frameCount'],record['frameCount'])
    timing['flightFamilySeconds']=time.perf_counter()-mark;mark=time.perf_counter()
    request=dict(source=record,windows=windows,recipeSha256=recipe_sha)
    if not cache_hit:
        write_new(directory/'dense-request.json',request)
        run_child([str(pose_python),str(worker),'dense','--video',str(video),
            '--config',str(config),'--request',str(directory/'dense-request.json'),
            '--output',str(directory/'dense.json')],directory/'dense-extraction.log')
    elif read(directory/'dense-request.json')!=request:
        raise ValueError('Cached dense request does not match fresh automatic proposals')
    progress('dense',record['frameCount'],record['frameCount'])
    dense=read(directory/'dense.json')
    if dense['requestSha256']!=sha(directory/'dense-request.json'):raise ValueError('Dense request provenance differs')
    items=validate_dense(dense,record,windows,recipe)
    timing['denseExtractionSeconds']=time.perf_counter()-mark;mark=time.perf_counter()
    progress("nominal",0,record["frameCount"])
    for item,window in zip(items,windows):
        x,quality=windows_api.nominal_features(item,window)
        row=next(r for r in rows if r['id']==window['candidateId']);row['nominalQuality']=quality
        nominal=models['nominal'];scores=score_classifier(nominal['model'],transform(x[None],nominal['state']))[0]
        if not np.isfinite(scores).all():raise ValueError('Nonfinite nominal inference')
        raw_nominal=str(nominal['model']['classes'][scores.argmax()])
        row.update(rawNominalProposal=raw_nominal,nominalScoresUncalibrated=dict(zip(nominal['model']['classes'].tolist(),scores.tolist())))
        if not nominal_usable(quality):
            row['nominalReason']='insufficient_torso_or_spectral_observations';continue
        row.update(nominal=raw_nominal,nominalReason='research_model_proposal')
    progress('nominal',record['frameCount'],record['frameCount'])
    timing['nominalInferenceSeconds']=time.perf_counter()-mark
    if sha(video)!=source_sha or sha(config)!=recipe_sha:raise ValueError('Original inputs changed during inference')
    check_recipe(recipe,config)
    if not cache_hit:
        write_new(cache_receipt,dict(sourceSha256=source_sha,recipeSha256=recipe_sha,
            filesSha256={n:sha(directory/n) for n in ['timeline.json','sparse.json','dense-request.json','dense.json']}))
    overlap={role:source_sha in row['trainingSourceHashes'] for role,row in recipe['models'].items()}
    timing['totalBeforeWriteSeconds']=time.perf_counter()-started
    return dict(schemaVersion=1,status='completed',inferenceScope='whole_source',sourceSha256=source_sha,
        sourcePath=str(video),sourceMetadata={k:v for k,v in record.items() if k!='timestampsSeconds'},
        recipePath=str(config),recipeSha256=recipe_sha,mode=recipe['mode'],recipeGroup=recipe['groupId'],
        poseSha256=recipe['poseSha256'],detectorSha256=recipe['detectorSha256'],models=recipe['models'],
        events=rows,timings=timing,cacheHit=cache_hit,cacheDirectory=str(directory),
        cacheManifestSha256=sha(cache_receipt),exactSourceTrainingOverlap=overlap,
        ortThreads=ort_threads(recipe),runtimeSessions=dict(sparse=sparse_document.get('runtimeSessions'),dense=read(directory/'dense.json').get('runtimeSessions')),
        globalAthleteIndependenceVerified=False,goal70Verified=False,underrotation=None,physicalAirborneTurns=None,
        limitations=['One fixed development bundle, not the source-specific grouped11-video control',
            'Training overlap is disclosed; no independent70% claim',
            'Offline future context; nominal class is not physical airborne turn measurement',
            'No underrotation or blade-contact certificate; cache runtime is not cold analysis'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video',type=Path)
    parser.add_argument('--config',type=Path,default=ROOT/'configs/axel-release-ort4-v2.json')
    parser.add_argument('--cache',type=Path,required=True)
    parser.add_argument('--pose-python',type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    if args.output.exists():raise ValueError('Preserve previous results; choose a new output')
    pose_python=args.pose_python or asset_path(args.config,read(args.config)["posePython"])
    result=run(args.video.resolve(),args.config.resolve(),args.cache.resolve(),executable_path(pose_python))
    progress("export",0,result["sourceMetadata"]["frameCount"])
    args.output.parent.mkdir(parents=True,exist_ok=True);write_new(args.output,result)
    progress('export',result['sourceMetadata']['frameCount'],result['sourceMetadata']['frameCount'])


if __name__=='__main__':main()
