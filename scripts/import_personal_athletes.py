"""Import explicit athlete identities separately from expert jump assessments."""
import argparse,hashlib,json,re
from pathlib import Path
from blind_rotation_evaluator import strict_loads
ROOT=Path(__file__).resolve().parents[1]

def validate_mapping(document,dataset):
 if type(document.get('schemaVersion')) is not int or document['schemaVersion']!=1 or document.get('datasetSha256')!=dataset['datasetSha256']:raise ValueError('Wrong schema or dataset')
 if set(document)!={'schemaVersion','datasetSha256','groups'} or not isinstance(document['groups'],list):raise ValueError('Expected groups only')
 items=dataset['items'];lookup={}
 for item in items:
  match=re.fullmatch(r'media/(\d{2})\.mp4',item['file'])
  if not match or int(match[1]) in lookup:raise ValueError('Ambiguous display video number')
  lookup[int(match[1])]=item
 if set(lookup)!=set(range(1,52)) or len({i['id'] for i in items})!=51 or len({i['sha256'] for i in items})!=51:raise ValueError('Expected51 unique videos')
 assigned={};groups=set()
 for group in document['groups']:
  if not isinstance(group,dict) or set(group)!={'athleteId','videoNumbers'}:raise ValueError('Invalid athlete row')
  name=group['athleteId'];numbers=group['videoNumbers']
  if not isinstance(name,str) or name!=name.strip() or not 1<=len(name)<=64 or any(ord(c)<32 for c in name):raise ValueError('Invalid athlete identity')
  if re.fullmatch(r'[1-4](?:A|А|Lz|F|Lo|T|S)(?:q|<|<<)?',name,re.I):raise ValueError('Jump code is not an athlete identity')
  if name in groups or not isinstance(numbers,list) or not numbers:raise ValueError('Duplicate athlete or empty video group')
  groups.add(name)
  for number in numbers:
   if type(number) is not int or number not in lookup or number in assigned:raise ValueError('Unknown or multiply assigned video')
   item=lookup[number];assigned[number]=dict(videoNumber=number,id=item['id'],sha256=item['sha256'],athleteId=name)
 return dict(schemaVersion=1,datasetSha256=dataset['datasetSha256'],assignments=[assigned[n] for n in sorted(assigned)],unassignedVideoNumbers=sorted(set(lookup)-set(assigned)),withinDatasetGroupingComplete=len(assigned)==51,athleteExclusionVerified=False,limitations=['User-supplied within-dataset identities; cross-corpus identity correspondence still requires verification.','No jump labels changed and no models trained.'])

def main():
 p=argparse.ArgumentParser();p.add_argument('--mapping',type=Path,required=True);p.add_argument('--dataset',type=Path,default=ROOT/'data/axel-demo-v1/personal-video-review/data.json');p.add_argument('--output',type=Path,default=ROOT/'data/personal-athletes-v1/imports');a=p.parse_args()
 raw=a.mapping.read_bytes();dataset_raw=a.dataset.read_bytes();dataset=strict_loads(dataset_raw);result=validate_mapping(strict_loads(raw),dataset)
 for item in dataset['items']:
  path=(a.dataset.parent/item['file']).resolve()
  if a.dataset.parent.resolve() not in path.parents or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Changed or escaped dataset media')
 digest=hashlib.sha256(raw).hexdigest();result.update(mappingSha256=digest,datasetFileSha256=hashlib.sha256(dataset_raw).hexdigest(),importerSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
 target=a.output/digest;payloads={'mapping.json':raw,'dataset.json':dataset_raw,'validated.json':json.dumps(result,ensure_ascii=False,indent=2).encode()}
 for name,payload in payloads.items():
  path=target/name
  if path.exists() and path.read_bytes()!=payload:raise ValueError('Refusing to overwrite previous import')
 target.mkdir(parents=True,exist_ok=True)
 for name,payload in payloads.items():
  if not (target/name).exists():(target/name).write_bytes(payload)
 print(json.dumps(dict(archive=str(target),assigned=len(result['assignments']),unassigned=len(result['unassignedVideoNumbers']))))
if __name__=='__main__':main()
