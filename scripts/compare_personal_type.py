"""Paired nominal-type transfer evaluation. No training and no rotation claims."""
import argparse,json,hashlib
from pathlib import Path
from import_personal_video_review import validate_review,AXELS
from evaluate_personal_blind import metrics

def compare(review,native,baseline,dataset):
 known={r['id']:r['sha256'] for r in dataset['items']}
 if len(known)!=51 or len(dataset['items'])!=51:raise ValueError('Expected51 unique items')
 tables={}
 for name,document in [('native',native),('baseline',baseline)]:
  if document.get('complete') is not True or document.get('datasetSha256')!=dataset['datasetSha256']:raise ValueError('Incomplete or mismatched dataset')
  table={}
  for r in document['records']:
   if r['id'] in table or r['id'] not in known or r['sha256']!=known[r['id']]:raise ValueError('Duplicate, unknown or changed media')
   value=r.get('typeProposal')
   if value not in AXELS|{'other','unclear','abstain',None}:raise ValueError('Unknown nominal type')
   table[r['id']]=value
  if set(table)!=set(known):raise ValueError('Missing predictions')
  tables[name]=table
 labels=[r for r in validate_review(review,dataset) if r['element']!='unclear']
 result=dict(scope='Nominal type only; no measured rotations or underrotation evaluated',athleteExclusionVerified=False,goal70Verified=False)
 def binary(v):return 'Axel' if v in AXELS else 'other' if v=='other' else None
 for name,table in tables.items():
  result[name]=dict(nominalType=metrics([(r['element'],table[r['id']]) for r in labels],['1A','2A','3A','other']),axelDetection=metrics([(binary(r['element']),binary(table[r['id']])) for r in labels],['Axel','other']))
 paired=dict(corrected=0,regressed=0,bothCorrect=0,bothWrong=0)
 for r in labels:
  a=tables['native'][r['id']]==r['element'];b=tables['baseline'][r['id']]==r['element'];paired['bothCorrect' if a and b else 'corrected' if a else 'regressed' if b else 'bothWrong']+=1
 result['pairedNominal']=paired;return result

def main():
 p=argparse.ArgumentParser()
 for name in ('review','native','baseline','dataset','output'):p.add_argument('--'+name,type=Path,required=True)
 a=p.parse_args();raw={k:getattr(a,k).read_bytes() for k in ('review','native','baseline','dataset')};docs={k:json.loads(v) for k,v in raw.items()}
 root=Path(__file__).resolve().parents[1]
 for source,digest in docs['native']['inputSha256'].items():
  if hashlib.sha256((root/source).read_bytes()).hexdigest()!=digest:raise ValueError('Frozen native input changed '+source)
 result=compare(**docs);result['inputSha256']={k:hashlib.sha256(v).hexdigest() for k,v in raw.items()};result['evaluatorSha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
 a.output.parent.mkdir(parents=True,exist_ok=True)
 with a.output.open('x') as stream:json.dump(result,stream,indent=2)
 print(json.dumps(result,indent=2))
if __name__=='__main__':main()
