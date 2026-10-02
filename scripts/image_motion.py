"""Translation-relative 2D flow descriptors, not angular or 3D rotation measurements."""
import numpy as np
PARTS=('shoulder','elbow','wrist','hip','knee','ankle')
def body_box(points,width=320,height=180):
    valid=[(p['x']*width,p['y']*height) for p in points if p['name'].split('_')[-1] in PARTS and p.get('confidence',0)>=.5 and 0<=p['x']<=1 and 0<=p['y']<=1]
    if len(valid)<6:return None
    a=np.array(valid);lo=a.min(0);hi=a.max(0);pad=(hi-lo)*.1
    return [max(0,float(lo[0]-pad[0])),max(0,float(lo[1]-pad[1])),min(width,float(hi[0]+pad[0])),min(height,float(hi[1]+pad[1]))]
def describe_flow(flow,box,dt):
    if not np.isfinite(dt) or dt<=0:raise ValueError('Positive frame interval required')
    if box is None:return np.full(3,np.nan)
    x0,y0,x1,y1=box;roi=flow[int(y0):int(y1),int(x0):int(x1)]
    if roi.size==0 or x1-x0<3 or y1-y0<3:return np.full(3,np.nan)
    vectors=roi.reshape(-1,2);vectors=vectors[np.isfinite(vectors).all(1)]
    if len(vectors)<10:return np.full(3,np.nan)
    # Remove common translation inside ROI; perspective/blur/occlusion still remain.
    residual=(vectors-np.median(vectors,axis=0))/(max(y1-y0,1)*dt)
    return np.array([np.mean(np.abs(residual[:,0])),np.mean(np.abs(residual[:,1])),np.percentile(np.linalg.norm(residual,axis=1),75)])
def pool_motion(rows,last_contact,first_contact):
    out=[]
    for lo,hi in [(last_contact,first_contact),(first_contact,first_contact+10)]:
        data=np.array([r['values'] for r in rows if lo<r['frameIndex']<=hi],dtype=float).reshape(-1,3)
        for j in range(3):
            valid=data[:,j][np.isfinite(data[:,j])]
            out.extend([float(valid.mean()),float(valid.std())] if len(valid) else [np.nan,np.nan])
    return np.array(out)
