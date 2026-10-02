"""Score explicitly supplied expert review against complete frozen predictions; never fit."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from import_personal_video_review import AXELS, validate_review


def digest(raw):return hashlib.sha256(raw).hexdigest()
def ratio(a,b):return a/b if b else None

def metrics(pairs,classes):
 support=Counter(t for t,p in pairs);correct=sum(t==p for t,p in pairs)
 recalls={c:ratio(sum(t==c and p==c for t,p in pairs),support[c]) for c in classes}
 present=[r for r in recalls.values() if r is not None]
 return dict(total=len(pairs),correct=correct,accuracy=ratio(correct,len(pairs)),support={c:support[c] for c in classes},recall=recalls,
             balancedRecall=sum(present)/len(present) if present else None,majorityBaseline=ratio(max(support.values(),default=0),len(pairs)),
             answered=sum(p in classes for t,p in pairs),coverage=ratio(sum(p in classes for t,p in pairs),len(pairs)))

def evaluate(review,predictions,dataset,protocol,dataset_file_sha):
 if len(dataset['items'])!=51 or len({r['id'] for r in dataset['items']})!=51:raise ValueError('Expected 51 unique dataset items')
 if predictions.get('complete') is not True:raise ValueError('Predictions incomplete')
 for key in ('schemaVersion','frozenAt','datasetSha256','datasetFileSha256','modelSha256','codeSha256','expectedCount','scope','evaluationPolicy'):
  if key not in protocol or predictions.get(key)!=protocol[key]:raise ValueError('Frozen protocol mismatch: '+key)
 if protocol['schemaVersion']!=1 or protocol['expectedCount']!=51 or protocol['datasetSha256']!=dataset['datasetSha256'] or protocol['datasetFileSha256']!=dataset_file_sha:raise ValueError('Dataset/protocol mismatch')
 rows=predictions.get('records');known={r['id']:r['sha256'] for r in dataset['items']};lookup={}
 if not isinstance(rows,list) or len(rows)!=51:raise ValueError('Expected exactly 51 predictions')
 for row in rows:
  identity=row.get('id')
  if identity not in known or identity in lookup or row.get('sha256')!=known[identity]:raise ValueError('Unknown, duplicate or changed prediction')
  if row.get('typeProposal') not in AXELS|{'other',None,'abstain','unclear'}:raise ValueError('Invalid type proposal')
  if row.get('rotationAssessment') not in {None,'apparently_complete','apparently_short'}:raise ValueError('Invalid rotation proposal')
  lookup[identity]=row
 labels=validate_review(review,dataset)
 if not labels:raise ValueError('No explicit expert labels; accuracy is undefined')
 explicit=[r for r in labels if r['element']!='unclear'];clear=[r for r in explicit if r['element'] in AXELS and r['rotation'] in {'complete','short'}]
 def typ(r):return lookup[r['id']].get('typeProposal')
 def rot(r):
  p=lookup[r['id']]
  # Frozen deployment supports rotation only for a proposed 2A; refusals stay wrong.
  if r['element']!='2A' or p.get('status')=='abstention' or p.get('typeProposal')!='2A':return None
  return {'apparently_complete':'complete','apparently_short':'short'}.get(p.get('rotationAssessment'))
 nominal=metrics([(r['element'],typ(r)) for r in explicit],['1A','2A','3A','other'])
 binary=metrics([('Axel' if r['element'] in AXELS else 'other','Axel' if typ(r) in AXELS else 'other' if typ(r)=='other' else None) for r in explicit],['Axel','other'])
 rotation=metrics([(r['rotation'],rot(r)) for r in clear],['complete','short'])
 groups=Counter(r['athleteGroup'] for r in labels if r['athleteGroup'])
 return dict(schemaVersion=1,status='descriptive_frozen_prediction_evaluation_not_verified_athlete_holdout',athleteExclusionVerified=False,goal70Verified=False,
             reviewed=len(labels),unreviewed=51-len(labels),unclearType=sum(r['element']=='unclear' for r in labels),unclearRotation=sum(r['rotation']=='unclear' for r in labels),
             nominalType=nominal,axelDetection=binary,rotation=rotation,
             rotationByNominalType={element:metrics([(r['rotation'],rot(r)) for r in clear if r['element']==element],['complete','short']) for element in sorted(AXELS)},
             nominalAndRotation=dict(total=len(clear),correct=sum(typ(r)==r['element'] and rot(r)==r['rotation'] for r in clear),accuracy=ratio(sum(typ(r)==r['element'] and rot(r)==r['rotation'] for r in clear),len(clear))),
             grouping=dict(missing=sum(r['athleteGroup'] is None for r in labels),groups=len(groups),support=dict(groups)),
             limitations=['Anonymous athlete codes do not verify exclusion across training and evaluation corpora.','Unclear and unanswered truths are not negative examples.','All expert-clear Axels remain in rotation denominator, including unsupported classes and refusals.','Nominal type is not measured revolution count; no angle accuracy is evaluated.'])

def main():
 p=argparse.ArgumentParser()
 for name in ('review','predictions','dataset','protocol','output'):p.add_argument('--'+name,required=True,type=Path)
 a=p.parse_args();raw={name:getattr(a,name).read_bytes() for name in ('review','predictions','dataset','protocol')};docs={k:json.loads(v) for k,v in raw.items()}
 result=evaluate(docs['review'],docs['predictions'],docs['dataset'],docs['protocol'],digest(raw['dataset']))
 result['provenance']={k+'FileSha256':digest(v) for k,v in raw.items()}
 result['provenance'].update(evaluatorSha256=digest(Path(__file__).read_bytes()),reviewValidatorSha256=digest(Path(__file__).with_name('import_personal_video_review.py').read_bytes()),frozenProtocolMatched=True,frozenModels=docs['protocol']['modelSha256'],frozenCode=docs['protocol']['codeSha256'])
 payload=json.dumps(result,ensure_ascii=False,indent=2).encode()
 a.output.parent.mkdir(parents=True,exist_ok=True)
 if a.output.exists() and a.output.read_bytes()!=payload:raise ValueError('Refusing to overwrite different evaluation artifact')
 if not a.output.exists():a.output.write_bytes(payload)
 print(str(a.output))
if __name__=='__main__':main()
