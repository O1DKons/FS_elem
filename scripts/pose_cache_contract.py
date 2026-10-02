"""Strict legacy COCO17 native-cache adapter; expectations come from the consumer.

The source is decoded read-only to validate coverage and observed timestamps.
No model is loaded. OpenCV is required for the default source probe (pose env).
"""
import hashlib
import json
from pathlib import Path
import numpy as np

REQUIRED=('pose_sha256','detector_sha256','native_extraction_sha256','sampling','recordingMode')

def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as stream:
  for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
 return h.hexdigest()

def probe_video_timeline(path):
 import cv2
 cap=cv2.VideoCapture(str(path));times=[]
 try:
  if not cap.isOpened():raise ValueError('Cannot open source')
  fps=float(cap.get(cv2.CAP_PROP_FPS))
  while True:
   ok,_=cap.read()
   if not ok:break
   times.append(float(cap.get(cv2.CAP_PROP_POS_MSEC))/1000)
 finally:cap.release()
 return {'fps':fps,'times':np.asarray(times)}

def validate_pose_cache(video_path,cache_path,expected_contract):
 """Validate a legacy complete-video cache; reject VFR/unavailable timestamps.

Returns verification metadata only, not a quality/accuracy assertion. Source
fingerprint is checked before and after decoding. NaN missing points are allowed;
score values above one are allowed because RTM scores are not probabilities.
 """
 if not isinstance(expected_contract,dict) or any(not isinstance(expected_contract.get(k),str) or not expected_contract[k] for k in REQUIRED):
  raise ValueError('Explicit consumer pose contract required')
 source_hash=sha(video_path);cache_hash=sha(cache_path)
 with np.load(cache_path,allow_pickle=False) as d:
  provenance=json.loads(str(d['provenance']))
  if any(provenance.get(k)!=v for k,v in expected_contract.items()):raise ValueError('Pose/model provenance mismatch')
  if str(d['source_sha256'])!=source_hash:raise ValueError('Source mismatch')
  points=d['points'];scores=d['scores'];idx=d['frame_indices'];times=d['times'];fps=float(d['fps'])
  n=len(points)
  if points.shape!=(n,17,2) or scores.shape!=(n,17) or not n:raise ValueError('Invalid COCO17 arrays')
  if np.isinf(points).any() or not np.isfinite(scores).all():raise ValueError('Invalid pose values')
  if not np.isfinite(fps) or fps<=0:raise ValueError('Invalid FPS')
  if idx.dtype.kind not in 'iu' or not np.array_equal(idx,np.arange(n)):raise ValueError('Incomplete frame indices')
  if times.shape!=(n,) or not np.allclose(times,np.arange(n)/fps,rtol=0,atol=1e-10):raise ValueError('Invalid cache timeline')
 timeline=probe_video_timeline(video_path);observed=np.asarray(timeline['times']);source_fps=timeline['fps']
 if not np.isfinite(source_fps) or abs(source_fps-fps)>max(1e-6,fps*1e-5):raise ValueError('Source FPS mismatch')
 if observed.shape!=(n,) or not np.isfinite(observed).all():raise ValueError('Source coverage mismatch')
 # Normalize source start; tolerate millisecond timestamp quantization only.
 if not np.allclose(observed-observed[0],times,rtol=0,atol=.002):raise ValueError('VFR or unavailable source timestamps unsupported')
 if sha(video_path)!=source_hash or sha(cache_path)!=cache_hash:raise ValueError('Inputs changed during validation')
 return {'sourceSha256':source_hash,'cacheSha256':cache_hash,'frameCount':n,'fps':fps,'durationSeconds':n/fps,'provenance':provenance,'timebase':'decoded OpenCV timestamps checked against nominal CFR; tolerance 2ms','compatible':True}
