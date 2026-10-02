"""Experimental fixed boundary augmentation. Not enabled in the baseline runtime."""
import math
import numpy as np
from axel_nominal import hip_features

OFFSETS=(-4,-2,0,2,4)


def boundary_windows(last_contact,first_contact):
    return [(last_contact+a,first_contact+b) for a in OFFSETS for b in OFFSETS]


def window_features(frames,last_contact,first_contact,fps):
    if (type(last_contact) is not int or type(first_contact) is not int
            or first_contact<=last_contact+1 or last_contact<0
            or not math.isfinite(fps) or fps<=0):
        raise ValueError('Invalid contact gap/timebase')
    hips,quality=hip_features(frames,last_contact,first_contact)
    quality['missingSourceFrames']=sum(str(i) not in frames for i in range(last_contact+1,first_contact))
    return np.r_[(first_contact-last_contact)/fps,hips],quality


def fit_weighted_ridge(x,y,event_weights,alpha=10.):
    x=np.asarray(x,float);y=np.asarray(y);weights=np.asarray(event_weights,float)
    if (x.ndim!=2 or len(x)!=len(y) or weights.shape!=(len(y),)
            or not np.isfinite(weights).all() or (weights<0).any() or weights.sum()<=0):
        raise ValueError('Invalid weighted training observations')
    valid=np.isfinite(x);weighted_valid=weights[:,None]*valid
    mean=np.divide((weights[:,None]*np.where(valid,x,0)).sum(0),weighted_valid.sum(0),
                   out=np.zeros(x.shape[1]),where=weighted_valid.sum(0)>0)
    filled=np.where(valid,x,mean)
    scale=np.sqrt((weights[:,None]*(filled-mean)**2).sum(0)/weights.sum())
    scale[scale<1e-8]=1
    z=(filled-mean)/scale;design=np.column_stack([z,np.ones(len(z))])
    classes=np.unique(y)
    if not set(classes)<=set(['1A','2A']):raise ValueError('Unsupported nominal labels')
    class_totals={c:float(weights[y==c].sum()) for c in classes}
    if any(v<=0 for v in class_totals.values()):raise ValueError('Zero-weight nominal class')
    balanced=np.array([weights[i]*weights.sum()/(len(classes)*class_totals[c]) for i,c in enumerate(y)])
    target=(y[:,None]==classes[None,:]).astype(float)
    penalty=np.eye(design.shape[1])*alpha;penalty[-1,-1]=0
    coefficients=np.linalg.solve(design.T@(balanced[:,None]*design)+penalty,
                                 design.T@(balanced[:,None]*target))
    return {'classes':classes,'mean':mean,'scale':scale,'weights':coefficients,'alpha':alpha,
            'trainingWeight':float(weights.sum()),'classWeight':class_totals}


def scores(model,x):
    x=np.atleast_2d(np.asarray(x,float));z=(np.where(np.isfinite(x),x,model['mean'])-model['mean'])/model['scale']
    return np.column_stack([z,np.ones(len(z))])@model['weights']


def consensus(predictions):
    if not predictions or any(p is None for p in predictions):
        return {'nominal':None,'reason':'insufficient_window_coverage'}
    if len(set(predictions))!=1:
        return {'nominal':None,'reason':'boundary_disagreement'}
    return {'nominal':predictions[0],'reason':None}


def predict_window(model,variant,frames,last_contact,first_contact,fps):
    if first_contact<=last_contact+1 or last_contact<0:
        return {'nominal':None,'reason':'invalid_contact_gap','quality':{}}
    x,quality=window_features(frames,last_contact,first_contact,fps)
    if variant=='constant':
        return {'nominal':model['label'],'reason':None,'quality':quality}
    if variant=='duration_hips' and (quality['missingSourceFrames'] or not np.isfinite(x[1:]).any()):
        return {'nominal':None,'reason':'insufficient_hip_observations','quality':quality}
    if variant not in ['duration','duration_hips']:raise ValueError('Unsupported variant')
    result=scores(model,x[:1] if variant=='duration' else x)[0]
    if not np.isfinite(result).all():raise ValueError('Non-finite nominal scores')
    return {'nominal':str(model['classes'][result.argmax()]),'reason':None,'quality':quality}
