"""Training-fold-only threshold selection, with the unchanged event geometry."""
from pathlib import Path
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'work/full-program-learned-flight-v1'))
from events import decode_events,evaluate_events


def decode(times,probability,usable,duration,threshold):
    if not np.isfinite(threshold) or not 0<threshold<1:
        raise ValueError('Threshold must be finite and strictly between zero and one')
    p=np.asarray(probability,float)
    # Validate originals with the fixed decoder before creating a threshold mask.
    decode_events(times,p,usable,duration)
    selected=np.where(np.isnan(p),np.nan,(p>threshold).astype(float))
    proposals=decode_events(times,selected,usable,duration)
    for row in proposals:
        first,last=row['startSample'],row['endSample']
        row['peakTime']=float(times[first+int(np.argmax(p[first:last+1]))])
    return proposals


def f2(rows):
    tp=sum(r['matchedEvents'] for r in rows)
    fn=sum(r['annotatedEvents']-r['matchedEvents'] for r in rows)
    fp=sum(r['falsePositiveCandidates'] for r in rows)
    denominator=5*tp+4*fn+fp
    return 5*tp/denominator if denominator else 0.


def choose(rows):
    return max(rows,key=lambda r:(r['f2'],r['threshold']))['threshold']


def assert_separation(records,train,heldout):
    if (set(train)&set(heldout) or sorted(train+heldout)!=list(range(len(records)))
            or len(train)!=len(set(train)) or len(heldout)!=len(set(heldout))):
        raise ValueError('Training and held-out indices must partition the pool')
    for key in ['athlete','sourceSha256','videoId']:
        if {records[i][key] for i in train}&{records[i][key] for i in heldout}:
            raise ValueError('Held-out '+key+' appears in training')


def select(inner_rows,thresholds):
    candidates=[]
    for threshold in thresholds:
        evaluations=[]
        for row in inner_rows:
            proposals=decode(row['times'],row['probability'],row['usable'],row['duration'],threshold)
            evaluations.append(evaluate_events(proposals,row['events'],row['duration'],True)['metrics'])
        candidates.append(dict(threshold=threshold,f2=f2(evaluations),innerMetrics=evaluations))
    return choose(candidates),candidates
