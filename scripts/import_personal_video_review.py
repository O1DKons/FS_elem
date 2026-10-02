"""Archive explicit personal-video expert labels; never train or infer labels."""
import argparse,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
AXELS={'1A','2A','3A'}

def validate_review(document,dataset):
 if document.get('schemaVersion')!=1 or document.get('datasetSha256')!=dataset['datasetSha256']:
  raise ValueError('Wrong review schema or dataset')
 if not isinstance(document.get('labels'),list):raise ValueError('Expected labels array')
 lookup={r['id']:r for r in dataset['items']};seen=set();result=[]
 for row in document['labels']:
  if not isinstance(row,dict):raise ValueError('Invalid label row')
  identity=row.get('id')
  if not isinstance(identity,str) or identity not in lookup or identity in seen:raise ValueError('Unknown or duplicate video')
  if row.get('sha256')!=lookup[identity]['sha256']:raise ValueError('Video hash mismatch')
  element=row.get('element');rotation=row.get('rotation');group=row.get('athleteGroup')
  if element not in AXELS|{'other','unclear'}:raise ValueError('Invalid element assessment')
  if element in AXELS:
   if rotation not in {'complete','short','unclear'}:raise ValueError('Axel needs explicit rotation assessment')
  elif rotation is not None:raise ValueError('Non-Axel or unclear type cannot have rotation assessment')
  if group is not None:
   if not isinstance(group,str) or len(group)>64 or any(ord(c)<32 for c in group):raise ValueError('Invalid anonymous athlete group')
   group=group.strip() or None
  seen.add(identity);result.append(dict(id=identity,sha256=row['sha256'],element=element,rotation=rotation,athleteGroup=group))
 return result

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--review',required=True,type=Path)
 parser.add_argument('--dataset',type=Path,default=ROOT/'data/axel-demo-v1/personal-video-review/data.json')
 parser.add_argument('--output',type=Path,default=ROOT/'data/personal-video-expert-v1/imports');args=parser.parse_args()
 raw=args.review.read_bytes();dataset_raw=args.dataset.read_bytes();dataset=json.loads(dataset_raw)
 rows=validate_review(json.loads(raw),dataset)
 for item in dataset['items']:
  media=(args.dataset.parent/item['file']).resolve()
  if args.dataset.parent.resolve() not in media.parents:raise ValueError('Media outside review directory')
  if hashlib.sha256(media.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Review media changed')
 digest=hashlib.sha256(raw).hexdigest();target=args.output/digest;target.mkdir(parents=True,exist_ok=True)
 for name,payload in [('review.json',raw),('dataset.json',dataset_raw)]:
  path=target/name
  if path.exists() and path.read_bytes()!=payload:raise ValueError('Archive collision')
  if not path.exists():path.write_bytes(payload)
 report=dict(schemaVersion=1,status='expert_labels_only_not_accuracy_or_training',reviewSha256=digest,
             datasetSha256=dataset['datasetSha256'],datasetFileSha256=hashlib.sha256(dataset_raw).hexdigest(),labels=rows,
             summary=dict(reviewed=len(rows),total=len(dataset['items']),clearRotation=sum(r['rotation'] in ('complete','short') for r in rows),
                          missingAthleteGroup=sum(r['athleteGroup'] is None for r in rows)),
             limitations=['Anonymous group codes still require consistent mapping across training and test sources.',
                          'No predictions, measured rotation angles, model fitting or accuracy claims are produced.'])
 (target/'validated.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(dict(archive=str(target),**report['summary'])))
if __name__=='__main__':main()
