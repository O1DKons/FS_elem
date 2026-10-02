"""Versioned baseline feature functions. No experiment execution or model loading."""
import hashlib
import inspect
import json
import numpy as np
from full_context_contact import features as base_features

OFFSETS=(-.2,-.1,0,.1,.2)

def flight_context_features(points,scores,fps):
 raw=base_features(points,scores,fps);n=len(raw);blocks=[]
 for offset in OFFSETS:
  ix=np.arange(n)+int(round(offset*fps));valid=(ix>=0)&(ix<n)
  block=np.full_like(raw,np.nan);block[valid]=raw[ix[valid]];blocks.append(block)
 return np.concatenate(blocks,axis=1)

def spectrum(signal):
 signal=np.asarray(signal,float);v=np.flatnonzero(np.isfinite(signal))
 if len(v)<.8*len(signal) or len(v)<4 or v[0]!=0 or v[-1]!=len(signal)-1 or np.diff(v).max()>3:return np.full(20,np.nan)
 z=np.interp(np.linspace(0,len(signal)-1,32),v,signal[v]);z-=z.mean()
 coef=np.fft.rfft(z)[1:11];power=np.abs(coef)**2
 power=power/power.sum() if power.sum()>1e-12 else np.zeros(10)
 corr=np.array([np.dot(z[:-k],z[k:])/max(np.dot(z,z),1e-12) for k in range(1,11)])
 return np.r_[power,corr]

def feature_contract():
 spec={'version':1,'flightOffsetsSeconds':OFFSETS,'flightOrder':'68 base geometry/velocity channels per offset','flightDimension':340,'spectrumOrder':'10 normalized Fourier powers then 10 autocorrelations','nominalOrder':'hips signed dx spectrum then signed dy spectrum','nominalDimension':40,'missing':'NaN; retain baseline preprocessing'}
 code=''.join(inspect.getsource(f) for f in [base_features,flight_context_features,spectrum])+json.dumps(spec,sort_keys=True)
 return dict(spec,codeSha256=hashlib.sha256(code.encode()).hexdigest())
