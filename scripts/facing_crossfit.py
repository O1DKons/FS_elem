"""Orientation predictions with explicit athlete exclusions; no identity as feature."""
import numpy as np
CLASSES=['front','back','side']
def predict_facing(x,y,groups,query,excluded):
 mask=np.array([g not in excluded for g in groups])
 used=np.flatnonzero(mask).tolist()
 output=np.full((len(query),3),np.nan)
 present=[c for c in CLASSES if np.any(y[mask]==c)]
 if not present:return output,used
 centers=np.array([x[mask][y[mask]==c].mean(0) for c in present])
 valid=np.isfinite(query).all(1)
 guesses=((query[valid,None,:]-centers[None,:,:])**2).sum(2).argmin(1)
 output[valid]=0
 for row,g in zip(np.flatnonzero(valid),guesses):output[row,CLASSES.index(present[g])]=1
 return output,used
