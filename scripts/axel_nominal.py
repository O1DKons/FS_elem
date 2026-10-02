"""Frozen 40D nominal inference on compatible RTMW source-frame windows."""
import numpy as np
from axel_features import spectrum
from axel_baseline_inference import compatible_nominal_pose
from run_rotation_proxy_baseline import transform
from video_type_model import score_classifier


def hip_features(frames,last_contact,first_contact):
    signal=[];usable=0
    for i in range(last_contact+1,first_contact):
        row=frames.get(str(i),{})
        points=np.asarray(row.get('points',[]));scores=np.asarray(row.get('scores',[]))
        valid=(points.ndim==2 and points.shape[1]==2 and len(points)>=17 and scores.ndim==1
               and len(scores)>=17 and np.isfinite(points[[11,12]]).all() and (scores[[11,12]]>=.5).all())
        signal.append(points[12]-points[11] if valid else [np.nan,np.nan]);usable+=int(valid)
    z=np.asarray(signal).reshape(-1,2)
    x=np.r_[spectrum(z[:,0]),spectrum(z[:,1])]
    return x,{'flightFrames':len(z),'usableHipFrames':usable,'finiteFeatures':int(np.isfinite(x).sum())}


def nominal_prediction(document,last_contact,first_contact,model,provenance,expected):
    compatible_nominal_pose(provenance,expected)
    x,qa=hip_features(document['frames'],last_contact,first_contact)
    if not np.isfinite(x).any():
        return {'nominal':None,'reason':'insufficient_hip_observations','quality':qa}
    scores=score_classifier(model['model'],transform(x[None],model['state']))[0]
    if not np.isfinite(scores).all():raise ValueError('Non-finite nominal model output')
    classes=model['model']['classes'];label=str(classes[scores.argmax()])
    if label not in ['1A','2A']:raise ValueError('Unsupported nominal class')
    return {'nominal':label,'reason':None,'quality':qa}
