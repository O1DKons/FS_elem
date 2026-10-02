"""Frame-scoped flight labels for reviews verified against the exact original source.

This is an opt-in versioned adapter. It never converts seconds-only reviews to
source frames and does not change frozen experiments or the baseline runtime.
"""
import numpy as np


def review_frame_labels(indices, events, complete, expected_source_sha, review_source_sha, frame_count):
    ix=np.asarray(indices)
    if (not isinstance(expected_source_sha,str) or len(expected_source_sha)!=64
            or expected_source_sha!=review_source_sha or type(complete) is not bool
            or type(frame_count) is not int or frame_count<1 or ix.ndim!=1 or len(ix)<1
            or not np.issubdtype(ix.dtype,np.integer) or np.any(ix<0) or np.any(ix>=frame_count)
            or np.any(np.diff(ix)<=0)):
        raise ValueError('Unverified source/frame review contract')
    y=np.full(len(ix),0 if complete else -1,dtype=np.int8)
    seen=set();confirmed=[];uncertain=[]
    for e in events:
        if e['id'] in seen:raise ValueError('Duplicate frame-reviewed event')
        seen.add(e['id']);a=e['lastContactFrame'];b=e['firstContactFrame']
        if type(a) is not int or type(b) is not int or not 0<=a<b<frame_count:
            raise ValueError('Invalid original-source contact frame')
        if e['eventClass']=='uncertain':uncertain.append((a,b));continue
        if e['eventClass'] not in ('axel','other_jump'):raise ValueError('Unsupported frame-reviewed event')
        if any(max(a,c)<min(b,d) for c,d in confirmed):raise ValueError('Overlapping confirmed source flights')
        confirmed.append((a,b));y[(ix>a)&(ix<b)]=1
    for a,b in confirmed:y[(ix==a)|(ix==b)]=-1
    for a,b in uncertain:y[(ix>=a)&(ix<=b)]=-1
    return y
