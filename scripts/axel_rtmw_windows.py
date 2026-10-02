"""RTMW23 extraction only in automatically proposed windows, one model load per job.

Uses the unchanged crop/tracking recipe from the dense competition experiment.
No annotations, event labels, or trained nominal classifier are read here.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import numpy as np
from pose_cache_contract import sha


def window_specs(events,fps,frame_count):
    out=[]
    for index,event in enumerate(events):
        if event['family']!='axel':continue
        start,end=event['startSeconds'],event['endSeconds']
        if not all(math.isfinite(v) for v in [start,end,fps]) or fps<=0 or not 0<=start<end<(frame_count/fps):
            raise ValueError('Invalid automatic interval')
        a,b=round(start*fps),round(end*fps)
        if abs(a/fps-start)>1e-7 or abs(b/fps-end)>1e-7:raise ValueError('Interval not on source frame grid')
        out.append({'eventIndex':index,'startSeconds':start,'endSeconds':end,'startFrame':a,'endFrame':b,
                    'cropStartFrame':max(0,a-30),'cropEndFrame':min(frame_count-1,b+20)})
    return out


def validate_window(document,source,fps,frame_count,window,expected):
    required=('pose_sha256','detector_sha256','extractor_sha256','geometry')
    if any(not expected.get(k) for k in required):raise ValueError('Explicit nominal extraction contract required')
    if (document.get('schemaVersion')!=1 or document.get('sourceSha256')!=source
        or document.get('fps')!=fps or document.get('frameCount')!=frame_count or document.get('window')!=window):
        raise ValueError('Wrong RTMW source/window metadata')
    if any(document.get('provenance',{}).get(k)!=v for k,v in expected.items()):raise ValueError('Wrong RTMW provenance')
    frames=document.get('frames',{})
    if set(frames)!={str(i) for i in range(window['cropStartFrame'],window['cropEndFrame']+1)}:
        raise ValueError('Incomplete RTMW window')
    for key,row in frames.items():
        i=int(key);points=np.asarray(row.get('points',[]));scores=np.asarray(row.get('scores',[]))
        if row.get('frameIndex')!=i or abs(row.get('time',-1)-i/fps)>1e-10:raise ValueError('Invalid RTMW timebase')
        if points.size==0 and scores.size==0:continue
        if points.shape!=(23,2) or scores.shape!=(23,) or np.isinf(points).any() or not np.isfinite(scores).all():
            raise ValueError('Invalid RTMW23 arrays')
    return document


def expanded_keypoint_box(points,scores,source_box,width,height):
    valid=[(float(p[0]),float(p[1])) for p,s in zip(points,scores)
           if math.isfinite(float(s)) and float(s)>=.5 and math.isfinite(float(p[0])) and math.isfinite(float(p[1]))]
    if len(valid)<6:return source_box
    xs,ys=[p[0] for p in valid],[p[1] for p in valid];padding=max(24.,.12*(max(ys)-min(ys)))
    box=[max(0.,min(xs)-padding),max(0.,min(ys)-padding),min(float(width-1),max(xs)+padding),min(float(height-1),max(ys)+padding)]
    return box if box[2]>box[0] and box[3]>box[1] else source_box


def extract_windows(video,cache,request,expected):
    import cv2
    from infer_jump_landmarks import DETECTOR,POSE,models,track_box
    source=request['sourceSha256'];fps=request['fps'];count=request['frameCount'];windows=request['windows']
    if sha(video)!=source:raise ValueError('Source changed before RTMW extraction')
    if sha(Path(__file__))!=expected['extractor_sha256']:raise ValueError('Nominal extractor changed')
    if sha(POSE)!=expected['pose_sha256'] or sha(DETECTOR)!=expected['detector_sha256']:raise ValueError('RTMW weights mismatch')
    cache.mkdir(parents=True,exist_ok=True);entries=[];pending=[]
    for w in windows:
        key=hashlib.sha256(json.dumps({'source':source,'fps':fps,'frames':count,'window':w,'contract':expected},sort_keys=True).encode()).hexdigest()
        path=cache/(key+'.json');entry={'eventIndex':w['eventIndex'],'path':str(path.resolve()),'cacheHit':path.exists()};entries.append(entry)
        if path.exists():validate_window(json.loads(path.read_text()),source,fps,count,w,expected)
        else:pending.append({'window':w,'path':path,'box':None,'frames':{}})
    if pending:
        detector,pose=models();cap=cv2.VideoCapture(str(video))
        if not cap.isOpened():raise ValueError('Cannot open RTMW source')
        width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH));height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if abs(cap.get(cv2.CAP_PROP_FPS)-fps)>1e-6:cap.release();raise ValueError('RTMW source FPS changed')
        end=max(v['window']['cropEndFrame'] for v in pending)
        try:
            for i in range(end+1):
                ok,image=cap.read()
                if not ok:raise ValueError('Premature RTMW source EOF')
                for state in pending:
                    w=state['window'];start=w['cropStartFrame']
                    if not start<=i<=w['cropEndFrame']:continue
                    previous=state['box']
                    if previous is None or (i-start)%5==0:previous=track_box(detector(image),previous)
                    row={'frameIndex':i,'time':i/fps,'decodedBgrSha256':hashlib.sha256(image.tobytes()).hexdigest(),'points':[],'scores':[]}
                    if previous is not None:
                        points,scores=pose(image,bboxes=[previous]);row['points']=points[0,:23].tolist();row['scores']=scores[0,:23].tolist()
                        previous=expanded_keypoint_box(row['points'],row['scores'],previous,width,height)
                    state['box']=previous;row['box']=None if previous is None else list(map(float,previous));state['frames'][str(i)]=row
        finally:cap.release()
        if sha(video)!=source:raise ValueError('Source changed during RTMW extraction')
        for state in pending:
            doc={'schemaVersion':1,'sourceSha256':source,'fps':fps,'frameCount':count,'window':state['window'],
                 'provenance':expected,'width':width,'height':height,'frames':state['frames']}
            validate_window(doc,source,fps,count,state['window'],expected)
            temp=state['path'].with_suffix('.tmp.json');temp.write_text(json.dumps(doc));temp.replace(state['path'])
    for entry in entries:entry['sha256']=sha(Path(entry['path']))
    return entries


def main():
    p=argparse.ArgumentParser();p.add_argument('video',type=Path);p.add_argument('request',type=Path);p.add_argument('config',type=Path);p.add_argument('cache',type=Path);p.add_argument('receipt',type=Path);a=p.parse_args()
    request=json.loads(a.request.read_text());expected=json.loads(a.config.read_text())['nominalPoseContract']
    entries=extract_windows(a.video,a.cache,request,expected)
    a.receipt.write_text(json.dumps({'entries':entries},indent=2))
if __name__=='__main__':main()
