"""Fixed v4 threshold mask and event decoder; no threshold selection or training."""
import numpy as np
from events import decode_events


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
