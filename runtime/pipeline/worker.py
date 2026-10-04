"""Generic full-video PTS probe and dense automatic RTMW windows; import is inert."""
import argparse
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
os.environ['OMP_NUM_THREADS']='2';os.environ['OPENBLAS_NUM_THREADS']='2'
from support import SCRIPTS, asset_path, progress, verify_display_geometry
from pose_cache_contract import sha
from source_diagnostics import require_source_timeline, SourceDiagnosticsError


def probe(video,recipe,config):
    import cv2
    capture=cv2.VideoCapture(str(video))
    fps=capture.get(cv2.CAP_PROP_FPS);count=int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    width,height=int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if not capture.isOpened() or fps<=0 or count<3 or count/fps>600:
        raise ValueError('Unsupported/missing video or exceeds600-second research limit')
    rotation=capture.get(cv2.CAP_PROP_ORIENTATION_META) if hasattr(cv2,"CAP_PROP_ORIENTATION_META") else None
    auto=bool(capture.get(cv2.CAP_PROP_ORIENTATION_AUTO)) if hasattr(cv2,"CAP_PROP_ORIENTATION_AUTO") else None
    progress("probe",0,count)
    times=[]
    while True:
        ok,image=capture.read()
        if not ok:break
        if image.shape[:2]!=(height,width):raise ValueError('Decoded source geometry changes or differs from metadata')
        times.append(capture.get(cv2.CAP_PROP_POS_MSEC)/1000)
        if len(times)%500==0:progress("probe",len(times),count)
    capture.release()
    require_source_timeline(count,times)
    ffmpeg=asset_path(config,recipe['ffmpeg']['path'])
    if sha(ffmpeg)!=recipe['ffmpeg']['sha256']:raise ValueError('Pinned FFmpeg changed')
    command=[str(ffmpeg),'-hide_banner','-nostdin','-i',str(video),'-map','0:v:0',
        '-vf','showinfo','-fps_mode','passthrough','-f','null','-']
    process=subprocess.run(command,capture_output=True,text=True,check=True)
    pairs=re.findall(r'\bn:\s*(\d+)\s+pts:\s*[-\d]+\s+pts_time:([-.\deE+]+)',process.stderr)
    if [int(i) for i,_ in pairs]!=list(range(count)):
        raise ValueError('FFmpeg source-frame coverage differs')
    sizes=[(int(w),int(h)) for w,h in re.findall(r'\bn:\s*\d+.*?\bs:(\d+)x(\d+)',process.stderr)]
    if len(sizes)!=count:raise ValueError('FFmpeg geometry coverage unverified')
    verification=verify_display_geometry(width,height,sizes,rotation,auto)
    progress('probe',count,count)
    agreement=max(abs(t-float(p)) for t,(_,p) in zip(times,pairs))
    if agreement>1e-5:raise ValueError('OpenCV/FFmpeg source PTS disagreement')
    return dict(sourceSha256=sha(video),sourcePath=str(video),fps=fps,frameCount=count,width=width,height=height,
        duration=times[-1],timestampsSeconds=times,maxDecoderAgreementSeconds=agreement,
        rotationDegrees=rotation,geometryVerification=verification,
        ffmpegSha256=recipe['ffmpeg']['sha256'],timeContract='complete-opencv-and-ffmpeg-source-PTS-v1',
        versions={n:importlib.metadata.version(n) for n in ['rtmlib','onnxruntime','opencv-python']})


def dense(video,request,recipe,request_sha,config):
    import cv2
    from pose_models import models,track_box,runtime_sessions
    DETECTOR=asset_path(config,recipe["checkpoints"]["detector"]["path"])
    POSE=asset_path(config,recipe["checkpoints"]["pose"]["path"])
    from axel_rtmw_windows import expanded_keypoint_box
    source=request['source']
    if sha(video)!=source['sourceSha256'] or sha(DETECTOR)!=recipe['detectorSha256'] or sha(POSE)!=recipe['poseSha256']:
        raise ValueError('Dense source/checkpoints changed')
    items=[dict(window=w,frames={},previous=None) for w in request['windows']]
    progress("dense",0,source["frameCount"])
    detector,pose=models(config,recipe) if items else (None,None)
    if items:
        capture=cv2.VideoCapture(str(video));n=0
        while True:
            ok,image=capture.read()
            if not ok:break
            if image.shape[:2]!=(source['height'],source['width']):raise ValueError('Dense original source geometry differs')
            timestamp=capture.get(cv2.CAP_PROP_POS_MSEC)/1000
            if n>=source['frameCount'] or abs(timestamp-source['timestampsSeconds'][n])>1e-6:
                raise ValueError('Dense source PTS differs from full probe')
            for item in items:
                window=item['window']
                if not window['cropStartFrame']<=n<=window['cropEndFrame']:continue
                box=item['previous']
                if box is None or (n-window['cropStartFrame'])%5==0:box=track_box(detector(image),box)
                row=dict(frameIndex=n,time=timestamp,decodedBgrSha256=hashlib.sha256(image.tobytes()).hexdigest(),points=[],scores=[])
                if box is not None:
                    points,scores=pose(image,bboxes=[box]);row.update(points=points[0,:23].tolist(),scores=scores[0,:23].tolist())
                    box=expanded_keypoint_box(row['points'],row['scores'],box,source['width'],source['height'])
                item['previous']=box;row['box']=None if box is None else list(map(float,box));item['frames'][str(n)]=row
            n+=1
            if n%500==0:progress("dense",n,source["frameCount"])
        capture.release()
        if n!=source['frameCount']:raise ValueError('Dense complete source decoding truncated')
    progress('dense',source['frameCount'],source['frameCount'])
    for item in items:del item['previous']
    if sha(video)!=source['sourceSha256']:raise ValueError('Original video changed')
    return dict(schemaVersion=1,geometry=dict(recipe['denseGeometry'],width=source['width'],height=source['height']),sourceSha256=source['sourceSha256'],fps=source['fps'],frameCount=source['frameCount'],
        poseSha256=recipe['poseSha256'],detectorSha256=recipe['detectorSha256'],
        requestSha256=request_sha,extractorSha256=sha(Path(__file__)),
        geometryVerification=source['geometryVerification'],rotationDegrees=source['rotationDegrees'],
        runtimeSessions=runtime_sessions(detector,pose),items=items)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['probe','dense'])
    parser.add_argument('--video',required=True,type=Path)
    parser.add_argument('--config',required=True,type=Path)
    parser.add_argument('--request',type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    if args.output.exists():raise ValueError('Output exists; never overwrite observations')
    recipe=json.loads(args.config.read_text())
    for package,version in recipe['poseVersions'].items():
        if importlib.metadata.version(package)!=version:raise ValueError('Pose environment differs: '+package)
    for path,digest in recipe['inputSha256'].items():
        if sha(asset_path(args.config,path))!=digest:raise ValueError('Pinned extraction input changed')
    result=probe(args.video,recipe,args.config) if args.mode=='probe' else dense(args.video,json.loads(args.request.read_text()),recipe,sha(args.request),args.config)
    with args.output.open('x') as stream:json.dump(result,stream,allow_nan=False)


if __name__=='__main__':
    try:main()
    except SourceDiagnosticsError as exc:
        print(json.dumps({'kind':'analysis_diagnostics','diagnostics':exc.diagnostics},allow_nan=False),flush=True)
        raise
