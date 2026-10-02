"""Experimental pivot classifier export/inference. Needs a verified contact and 50fps feet."""
import argparse,json,hashlib
from pathlib import Path
import numpy as np
from binary_pivot import pivot_features,FEATURES
from source_frame_reuse import independent_intervals
from run_rotation_proxy_baseline import fit_preprocessor,transform
ROOT=Path(__file__).resolve().parents[1]

def fit_model(x,y):
 if x.ndim!=2 or x.shape[1]!=len(FEATURES) or len(x)!=len(y) or set(y)!={0,1}:raise ValueError('Nine features and both binary classes required')
 state=fit_preprocessor(x);z=transform(x,state)
 return dict(**state,centroids=np.array([z[y==c].mean(0) for c in (0,1)]))

def predict_item(item,model,fps):
 if fps!=50:raise ValueError('Model requires standardized50fps, not source-frame rate')
 values=pivot_features(item);intervals=round(values[1]*10);evidence=independent_intervals(item)
 result=dict(status='insufficient_evidence',rotationAssessment=None,underrotationDegrees=None,measuredRevolutions=None,observedIntervals=intervals,windowFrames=11,**evidence)
 if not evidence['sourceProvenanceComplete']:
  result['reason']='Missing source-frame provenance; independent evidence cannot be established';return result
 if evidence['independentSourceIntervals']<3:
  result['reason']='Fewer than three valid adjacent intervals with a new source frame and changed image';return result
 distances=((transform(values[None,:],model)[0]-model['centroids'])**2).sum(1)
 result.update(status='experimental_proposal',rotationAssessment=['apparently_complete','apparently_short'][int(distances.argmin())],squaredDistances=distances.tolist(),reason='Image-plane skate motion classifier; not a physical angle or overall landing-quality assessment')
 return result

def main():
 parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='command',required=True)
 export=sub.add_parser('export');export.add_argument('--output',type=Path,default=ROOT/'work/landing-rotation-model/classifier.npz')
 infer=sub.add_parser('predict');infer.add_argument('--input',required=True,type=Path);infer.add_argument('--model',required=True,type=Path)
 args=parser.parse_args()
 if args.command=='export':
  source=ROOT/'work/binary_pivot/results.json';result=json.loads(source.read_text())
  for path,digest in result['inputSha256'].items():
   if hashlib.sha256((ROOT/path).read_bytes()).hexdigest()!=digest:raise ValueError('Stale training input')
  x=np.array([[np.nan if v is None else v for v in row] for row in result['features']]);y=np.array([r['truth'] for r in result['records']])
  model=fit_model(x,y);args.output.parent.mkdir(parents=True,exist_ok=True)
  np.savez_compressed(args.output,**model,featureNames=FEATURES,fps=50,trainingSourceSha256=[r['sourceSha256'] for r in result['records']],provenance=json.dumps(result),trainingResultSha256=hashlib.sha256(source.read_bytes()).hexdigest())
  print(str(args.output))
 else:
  document=json.loads(args.input.read_text());item=document['item']
  with np.load(args.model,allow_pickle=False) as artifact:
   if artifact['featureNames'].tolist()!=FEATURES:raise ValueError('Feature definition mismatch')
   result=predict_item(item,artifact,document['fps']);result['knownTrainingSource']=item.get('sourceSha256') in artifact['trainingSourceSha256'].tolist()
  result['modelSha256']=hashlib.sha256(args.model.read_bytes()).hexdigest();print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
if __name__=='__main__':main()
