"""Experimental calibrated contact prediction from cached native pose and runtime timing."""
import hashlib,json
from pathlib import Path
import numpy as np
from full_context_contact import features
from contact_timebase import resample_native
from phase_contact_pilot import decode
from run_rotation_proxy_baseline import transform
from video_native_type import validated_native
ROOT=Path(__file__).resolve().parents[1]

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def predict_contact(pose,cache_dir,manifest_path=None):
 import joblib
 path=Path(manifest_path or ROOT/'work/full-context-contact-deployment-v1/manifest.json')
 manifest=json.loads(path.read_text())
 for name,digest in manifest['inputSha256'].items():
  if sha(ROOT/name)!=digest:raise ValueError('Contact model contract changed: '+name)
 p,s,fps,indices,provenance,cache_sha=validated_native({'sha256':pose['sourceSha256']},Path(cache_dir))
 if provenance!=manifest['nativeProvenance']:raise ValueError('Native model provenance mismatch')
 p,s=resample_native(p,s,indices,pose)
 model=joblib.load(ROOT/manifest['classifier'])
 last,first=decode(model['model'].predict_proba(transform(features(p,s,50),model['state'])))
 adjusted=max(last+1,min(len(p)-1,first-manifest['correctionFrames50Hz']))
 return dict(status='experimental_contact_proposal',reviewRequired=True,predictedLastContact=int(last),predictedFirstContact=int(adjusted),uncalibratedFirstContact=int(first),correctionSeconds=manifest['correctionFrames50Hz']/50,fps=50,sourceSha256=pose['sourceSha256'],nativeCacheSha256=cache_sha,manifestSha256=sha(path),knownTrainingSource=pose['sourceSha256'] in manifest['trainingClipSha256'],scope='Known short single-jump clip; no no-jump rejection or end-to-end validation')
