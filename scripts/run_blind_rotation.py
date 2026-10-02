"""Frozen diagnostic; no labels are read, no models are fitted."""
import json,hashlib,subprocess,sys,argparse
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--run-dir',type=Path,default=ROOT/'work/blind-rotation-v1');parser.add_argument('--review-dir',type=Path,default=ROOT/'data/axel-demo-v1/rotation-video-review');args=parser.parse_args()
BASE=args.run_dir.resolve();REVIEW=args.review_dir.resolve()
protocol=json.loads((BASE/'protocol.json').read_text());data=json.loads((REVIEW/'data.json').read_text())
assert data['datasetSha256']==protocol['datasetSha256']
models={'type':'work/video-fusion-type-v1/classifier.joblib','contact':'work/phase-contact-rtmw/classifier.joblib','rotation':'work/landing-rotation-model/classifier.npz'}
for name,path in models.items():assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==protocol['modelSha256'][name]
for path,digest in protocol.get('codeSha256',{}).items():assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==digest
records=[]
for n,item in enumerate(data['items']):
 for name,path in models.items():assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==protocol['modelSha256'][name]
 for path,digest in protocol.get('codeSha256',{}).items():assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==digest
 source=REVIEW/item['file'];assert hashlib.sha256(source.read_bytes()).hexdigest()==item['sha256']
 out=BASE/'runs'/item['id'];resultfile=out/'result.json'
 if not resultfile.exists():
  out.parent.mkdir(exist_ok=True)
  with (BASE/f'{item["id"]}.log').open('w') as log:
   process=subprocess.run([sys.executable,str(ROOT/'scripts/analyze_axel_clip.py'),'--input',str(source),'--output',str(out)],stdout=log,stderr=subprocess.STDOUT)
 if resultfile.exists():
  result=json.loads(resultfile.read_text());assert result['sourceSha256']==item['sha256']
  for name,digest in result['modelSha256'].items():assert digest==protocol['modelSha256'][name]
  label=result['typeProposal']['predicted_label'];proposal=result.get('rotationProposal') or {}
  assessment=proposal.get('rotationAssessment') if label=='2A' else None
  row=dict(id=item['id'],sha256=item['sha256'],rotationAssessment=assessment,status='diagnostic_prediction' if assessment else 'abstention',typeProposal=label,contactProposal=result.get('contactProposal'),resultPath=str(resultfile.relative_to(ROOT)))
 else:row=dict(id=item['id'],sha256=item['sha256'],rotationAssessment=None,status='extraction_error')
 records.append(row)
 document=dict(protocol,records=records,complete=len(records)==len(data['items']))
 temp=BASE/'predictions.tmp';temp.write_text(json.dumps(document,ensure_ascii=False,indent=2));temp.replace(BASE/'predictions.json')
 print(f'{n+1}/{len(data["items"])} {row["status"]}',flush=True)
