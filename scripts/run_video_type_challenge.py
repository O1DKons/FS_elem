"""Untrained local-event challenge: all confirmed coarse Axel clips + three reviewed negatives.
Labels are used solely for scoring, not extraction or inference. Not a full-program test.
"""
import json,re,hashlib,argparse
import numpy as np
from pathlib import Path
from video_type_model import predict_clip,metrics
ROOT=Path(__file__).resolve().parents[1]
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--model',type=Path,required=True);args=parser.parse_args()
 paths=['data/step3-candidates/active-axels.json','data/step3-candidates/manifest.json','data/step3-candidates/user-review.json']
 loaded=[json.loads((ROOT/p).read_text()) for p in paths];active,manifest,review=loaded
 rows=[]
 for r in active['items']:
  match=re.match(r'^([1234]A)',r['protocolCode'])
  if not match:raise ValueError('Unexpected accepted type')
  rows.append((r,match.group(1),'confirmed Axel clip; nominal type from protocol, not measured rotation'))
 lookup={r['id']:r for r in manifest['items']}
 for aid in review['rejectedNoJump']+review['outOfScope']:
  rows.append((lookup[aid],'other','explicit user no-jump or non-Axel review'))
 with np.load(args.model,allow_pickle=False) as artifact:
  training=json.loads(str(artifact['provenance']))['records']
 training_hashes={r['sha256'] for r in training}
 results=[]
 for r,truth,source in rows:
  path=ROOT/'data/step3-candidates'/r['clip'];digest=hashlib.sha256(path.read_bytes()).hexdigest()
  if digest!=r['clipSha256']:raise ValueError('Clip hash mismatch')
  if digest in training_hashes:raise ValueError('Exact training video in challenge')
  prediction=predict_clip(path,args.model)
  results.append(dict(attemptId=r['id'],truth=truth,truthSource=source,prediction=prediction))
 out=ROOT/'work/video-type-challenge';out.mkdir(parents=True,exist_ok=True)
 result=dict(records=results,metrics=metrics([r['truth'] for r in results],[r['prediction']['predicted_label'] for r in results]),inputSha256={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths},modelSha256=hashlib.sha256(args.model.read_bytes()).hexdigest(),scope='Local-event challenge: no identical training clip SHA; athlete/source overlap across differently encoded clips is not verified. 23 confirmed Axel windows plus three explicit negatives. Coarse multi-second clips, not exhaustive full-program test. Nominal type from protocol; no measured rotations or underrotation target. No parameter tuning on these outcomes.')
 (out/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False));print(json.dumps(result['metrics'],indent=2))
if __name__=='__main__':main()
