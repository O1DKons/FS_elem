"""Fixed development experiment. Labels never enter image features."""
import re
import numpy as np
from run_rotation_proxy_baseline import athlete_folds,fit_preprocessor,transform
CLASSES=['2A','2Aq','2A<','2A<<']
def explicit_label(record):
    text=record.get('notes','').replace('\u0410','A')
    found=set(re.findall(r'(?<!\w)2A(?:<<|<|q)?(?![A-Za-z<])',text))
    if len(found)!=1:return None
    label=found.pop()
    expected='apparently_complete' if label=='2A' else 'apparently_short'
    return label if record.get('rotationAssessment')==expected else None

def features(item):
    # Fixed 0..200ms window at native 50fps; periodic representation avoids wrap artefacts.
    rows=[]
    for frame in item['frames']:
        if not item['firstContact']<=frame['frameIndex']<=item['firstContact']+10:continue
        c=next((c for c in frame['candidates'] if c['side']=='landing'),None)
        if c is None or c['status']!='visible':continue
        v=np.asarray(c['toe'])-np.asarray(c['heel'])
        length=np.linalg.norm(v)
        if length>0:rows.append((frame['frameIndex'],v/length,length))
    output=[len(rows)/11]
    for start,end in [(0,4),(5,10)]:
        subset=[r for r in rows if start<=r[0]-item['firstContact']<=end]
        output.extend(np.mean([r[1] for r in subset],axis=0).tolist() if subset else [np.nan,np.nan])
    return output

def evaluate_signs(x,y,groups):
    predicted=[None]*len(y);folds=[];majority=[None]*len(y)
    for train,test in athlete_folds(groups):
        state=fit_preprocessor(x[train]);a=transform(x[train],state);b=transform(x[test],state)
        present=sorted(set(y[train]));centroids=np.array([a[y[train]==c].mean(axis=0) for c in present])
        guesses=((b[:,None,:]-centroids[None,:,:])**2).sum(axis=2).argmin(axis=1)
        counts={c:int(sum(y[train]==c)) for c in present};common=max(present,key=lambda c:counts[c])
        for i,g in zip(test,guesses):predicted[i]=present[g];majority[i]=common
        folds.append(dict(trainIndices=train.tolist(),testIndices=test.tolist(),trainingCounts=counts,missingClasses=[c for c in CLASSES if c not in present]))
    def score(p):
        recalls={c:sum(a==c and b==c for a,b in zip(y,p))/sum(y==c) for c in sorted(set(y))}
        return dict(correct=sum(a==b for a,b in zip(y,p)),total=len(y),macroRecall=float(np.mean(list(recalls.values()))),recall=recalls)
    return dict(predictions=predicted,metrics=score(predicted),majorityMetrics=score(majority),folds=folds)

def flight_features(rows,last_contact,first_contact):
    # Each flow row describes n-1 -> n. Both images must be airborne.
    values=np.array([r['values'] for r in rows if last_contact+1<r['frameIndex']<first_contact],dtype=float).reshape(-1,3)
    out=[]
    for j in range(3):
        valid=values[:,j][np.isfinite(values[:,j])]
        out.extend([float(valid.mean()),float(valid.std())] if len(valid) else [np.nan,np.nan])
    return out
