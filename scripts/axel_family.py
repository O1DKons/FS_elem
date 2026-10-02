"""Experimental RTMW 545D approach/flight/landing features; baseline unchanged."""
import numpy as np
from full_context_contact import features as body_features

RTMW_WEIGHTS='bd033156e5104c4f5d2edfe0453e02661e30a2f3da453ec93c8764d561b83054'


def segment_features(body,times,usable,start,end):
    body=np.asarray(body,float);times=np.asarray(times,float);usable=np.asarray(usable,bool)
    if (body.shape!=(len(times),68) or usable.shape!=times.shape
            or not np.isfinite([start,end]).all() or end<=start):
        raise ValueError('Invalid family interval/arrays')
    bins=np.linspace(start-.6,end+.3,9);chunks=[]
    for j in range(8):
        selected=usable&(times>=bins[j])&(times<bins[j+1]);x=body[selected]
        finite=np.isfinite(x);count=finite.sum(0)
        chunks.extend(np.divide(np.where(finite,x,0).sum(0),count,
                                out=np.full(68,np.nan),where=count>0))
    return np.r_[chunks,end-start]


def dense_features(document,start,end):
    if document.get('weightsSha256')!=RTMW_WEIGHTS:raise ValueError('Incompatible family pose weights')
    fps=document['fps'];frames=document['frames'];indices=np.array(sorted(map(int,frames)))
    if len(indices)<3 or not np.array_equal(indices,np.arange(indices[0],indices[-1]+1)):
        raise ValueError('Family requires contiguous source frames')
    points=np.full((len(indices),17,2),np.nan);scores=np.zeros((len(indices),17))
    for k,index in enumerate(indices):
        row=frames[str(index)]
        if row.get('missing') is True or not row.get('points'):continue
        p=np.asarray(row['points'],float);s=np.asarray(row['scores'],float)
        if p.shape!=(23,2) or s.shape!=(23,) or not np.isfinite(p).all() or not np.isfinite(s).all():
            raise ValueError('Malformed family pose')
        points[k]=p[:17];scores[k]=s[:17]
    raw=body_features(points,scores,fps)
    usable=np.isfinite(points[:,[5,6,11,12]]).all((1,2))&(scores[:,[5,6,11,12]]>=.3).all(1)
    times=indices/fps;x=segment_features(raw,times,usable,start,end)
    bins=np.linspace(start-.6,end+.3,9)
    quality={'sourceFrames':len(indices),'finiteFeatures':int(np.isfinite(x).sum()),
             'usableContextFramesByBin':[int((usable&(times>=bins[j])&(times<bins[j+1])).sum()) for j in range(8)],
             'firstFrame':int(indices[0]),'lastFrame':int(indices[-1]),
             'scope':'Usable torso is not proof of correct limbs or anatomical identity'}
    return x,quality
