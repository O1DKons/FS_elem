"""Frozen native-time nominal type inference for one short clip. No fitting."""
import argparse
import hashlib
import inspect
import json
from pathlib import Path
import numpy as np
from video_native_type import ROOT,OUTPUT,feature_contract,native_features,validated_native
from video_type_model import sha,fit_classifier,score_classifier


def load_model(path):
 with np.load(path,allow_pickle=False) as artifact:
  model={k:artifact[k] for k in ('classes','mean','std','weights','method')}
  provenance=json.loads(str(artifact['provenance']))
 if provenance.get('contract')!=feature_contract():raise ValueError('Native feature/runtime contract mismatch')
 expected=hashlib.sha256((inspect.getsource(fit_classifier)+inspect.getsource(score_classifier)).encode()).hexdigest()
 if provenance.get('classifier_code_sha256')!=expected:raise ValueError('Classifier implementation changed')
 if model['mean'].shape!=(208,) or model['std'].shape!=(208,) or set(model['classes'].tolist())!={'1A','2A','3A','other'}:raise ValueError('Invalid native classifier dimensions/classes')
 return model,provenance


def predict_clip(video,artifact_path=OUTPUT/'classifier.npz',cache_dir=None):
 video=Path(video);artifact_path=Path(artifact_path)
 model,provenance=load_model(artifact_path);source_sha=sha(video)
 cache=Path(cache_dir) if cache_dir is not None else ROOT/'phase-cache/video-pose-dense-inference-v2'
 path=cache/(source_sha+'.npz')
 if not path.exists():
  from extract_dense_pose_type import extract
  extract(video,cache)
 points,scores,fps,indices,native_provenance,cache_sha=validated_native({'sha256':source_sha},cache)
 if native_provenance!=provenance['native_provenance']:raise ValueError('Native pose provenance changed')
 if sha(video)!=source_sha:raise ValueError('Video changed during inference')
 feature,details=native_features(points,scores,fps,indices)
 result=dict(video_sha256=source_sha,predicted_label='abstain',raw_scores={},classes=model['classes'].tolist(),extraction_status='insufficient_pose',
             model_sha256=sha(artifact_path),provenance=dict(feature_contract=feature_contract(),native=native_provenance,native_cache_sha256=cache_sha,classifier_code_sha256=provenance['classifier_code_sha256']),
             details=details,type_seen_training_clip=any(r['sha256']==source_sha for r in provenance['records']),
             limitations=['Nominal class is not measured revolution count.','No underrotation angle or clean/short landing is predicted.','Short single-element input only; no full-program detection.','Source-disjointness does not establish athlete-disjoint validation.'])
 if feature is not None:
  values=score_classifier(model,feature[None,:])[0]
  if not np.isfinite(values).all():raise ValueError('Nonfinite classifier scores')
  result.update(predicted_label=str(model['classes'][np.argmax(values)]),raw_scores={str(c):float(v) for c,v in zip(model['classes'],values)},extraction_status='ok')
 return result


def main():
 p=argparse.ArgumentParser();p.add_argument('--input',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
 p.add_argument('--model',type=Path,default=OUTPUT/'classifier.npz');p.add_argument('--cache',type=Path)
 a=p.parse_args();result=predict_clip(a.input,a.model,a.cache);a.output.parent.mkdir(parents=True,exist_ok=True)
 a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False));print(json.dumps(dict(predicted_label=result['predicted_label'],extraction_status=result['extraction_status'],output=str(a.output))))
if __name__=='__main__':main()
