"""Strict scoring of frozen blind rotation predictions against partial expert review.

No training, prediction modification, label inference, or exclusion of abstentions.
"""
import argparse,hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DATASET=ROOT/'data/axel-demo-v1/rotation-video-review/data.json'
CLASSES=('complete','short')
MAP={'apparently_complete':'complete','apparently_short':'short',None:None}

def digest(path):
 h=hashlib.sha256()
 with path.open('rb') as stream:
  for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
 return h.hexdigest()

def require(condition,message):
 if not condition:raise ValueError(message)

def sha_valid(value):return isinstance(value,str) and re.fullmatch('[0-9a-f]{64}',value) is not None

def header(document,name,dataset_sha=None):
 require(isinstance(document,dict),name+' must be an object')
 require(type(document.get('schemaVersion')) is int and document['schemaVersion']==1,name+' schemaVersion must be integer1')
 require(sha_valid(document.get('datasetSha256')),name+' invalid dataset SHA256')
 if dataset_sha is not None:require(document['datasetSha256']==dataset_sha,name+' dataset SHA256 mismatch')

def validate_rows(rows,items,name,value_key,allowed):
 require(isinstance(rows,list),name+' rows must be a list');result={}
 for row in rows:
  require(isinstance(row,dict),name+' row must be object')
  key=row.get('id');require(isinstance(key,str) and key in items,name+' unknown id')
  require(key not in result,name+' duplicate id '+key)
  require(row.get('sha256')==items[key]['sha256'],name+' item SHA256 mismatch '+key)
  require(value_key in row and (row[value_key] is None or isinstance(row[value_key],str)) and row[value_key] in allowed,name+' invalid '+value_key)
  result[key]=row
 return result

def evaluate(dataset,labels,predictions,media_root):
 header(dataset,'dataset');items=dataset.get('items');require(isinstance(items,list) and len(items)>0,'dataset items must be a nonempty list')
 # This is exactly build_rotation_video_review.py's canonicalization.
 expected=hashlib.sha256(json.dumps(items,sort_keys=True).encode()).hexdigest()
 require(expected==dataset['datasetSha256'],'dataset item manifest hash mismatch')
 byid={};seen_sha=set();media_hashes={};media_root=Path(media_root).resolve()
 for row in items:
  require(isinstance(row,dict),'dataset row must be object');key=row.get('id')
  require(isinstance(key,str) and bool(key),'dataset id must be nonempty string');require(key not in byid,'duplicate dataset id')
  require(sha_valid(row.get('sha256')),'dataset invalid item SHA256');require(row['sha256'] not in seen_sha,'duplicate dataset video SHA256')
  require(isinstance(row.get('file'),str) and bool(row['file']) and not Path(row['file']).is_absolute(),'dataset file must be relative path')
  path=(media_root/row['file']).resolve()
  try:path.relative_to(media_root)
  except ValueError:raise ValueError('dataset media path escapes root')
  require(path.is_file(),'dataset video missing '+row['file']);actual=digest(path)
  require(actual==row['sha256'],'dataset video SHA256 mismatch '+key)
  byid[key]=row;seen_sha.add(actual);media_hashes[row['file']]=actual
 header(labels,'labels',expected);header(predictions,'predictions',expected)
 require(predictions.get('complete') is True,'Predictions must be finalized with complete=true')
 models=predictions.get('modelSha256');require(isinstance(models,dict) and bool(models),'modelSha256 must be a nonempty dictionary')
 require(all(isinstance(k,str) and bool(k) and sha_valid(v) for k,v in models.items()),'invalid model SHA256 dictionary')
 labelled=validate_rows(labels.get('labels'),byid,'labels','assessment',('complete','short','unclear'))
 predicted=validate_rows(predictions.get('records'),byid,'predictions','rotationAssessment',MAP)
 require(set(predicted)==set(byid),'predictions must cover every dataset id exactly once')
 for row in predicted.values():require(isinstance(row.get('status'),str) and bool(row['status']),'prediction status must be nonempty string')
 rows=[];confusion={c:{p:0 for p in (*CLASSES,'abstain')} for c in CLASSES}
 for key,item in byid.items():
  truth=labelled[key]['assessment'] if key in labelled else None;prediction=MAP[predicted[key]['rotationAssessment']];scored=truth in CLASSES
  if scored:confusion[truth][prediction if prediction is not None else 'abstain']+=1
  rows.append(dict(id=key,sha256=item['sha256'],expertAssessment=truth,prediction=prediction,predictionStatus=predicted[key]['status'],scored=scored,correct=(prediction==truth) if scored else None,excludedReason=None if scored else ('unclear_expert_label' if truth=='unclear' else 'missing_expert_label')))
 per_class={}
 for c in CLASSES:
  support=sum(confusion[c].values());correct=confusion[c][c]
  per_class[c]=dict(total=support,correct=correct,abstentions=confusion[c]['abstain'],recall=correct/support if support else None)
 total=sum(v['total'] for v in per_class.values());correct=sum(v['correct'] for v in per_class.values());abstain=sum(v['abstentions'] for v in per_class.values());both=all(per_class[c]['total']>0 for c in CLASSES)
 majority=max(CLASSES,key=lambda c:per_class[c]['total']) if total else None;majority_correct=per_class[majority]['total'] if majority else 0
 counts=dict(datasetItems=len(items),submittedLabels=len(labelled),missingLabels=len(items)-len(labelled),unclearLabels=sum(r['assessment']=='unclear' for r in labelled.values()),clearLabels=total,predictionRecords=len(predicted),allVideoAbstentions=sum(r['rotationAssessment'] is None for r in predicted.values()))
 metrics=dict(total=total,correct=correct,accuracy=correct/total if total else None,balancedAccuracy=sum(per_class[c]['recall'] for c in CLASSES)/2 if both else None,answered=total-abstain,abstentions=abstain,predictionCoverage=(total-abstain)/total if total else None,perClass=per_class,confusion=confusion)
 return dict(schemaVersion=1,datasetSha256=expected,modelSha256=dict(models),counts=counts,metrics=metrics,majorityBaseline=dict(classProposal=majority,total=total,correct=majority_correct,accuracy=majority_correct/total if total else None,balancedAccuracy=.5 if both else None,method='Post-hoc constant majority of clear expert labels; tie complete. Descriptive imbalance baseline, not trained independent model.'),records=rows,verifiedMediaSha256=media_hashes,
  scope='Frozen external binary review scoring only. Missing/unclear expert labels excluded explicitly; model abstentions count wrong for every clear expert label. Partial review is not complete dataset accuracy. Athlete identities unverified; type-model training used these videos, binary-model externality depends on frozen provenance. No degrees or new accuracy threshold claim.')

def strict_loads(raw):
 def object_pairs(pairs):
  result={}
  for key,value in pairs:
   require(key not in result,'Duplicate JSON property '+key);result[key]=value
  return result
 return json.loads(raw,object_pairs_hook=object_pairs,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('Nonfinite JSON value '+x)))

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--labels',type=Path,required=True);parser.add_argument('--predictions',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
 require(not args.output.exists(),'Output exists; use a new path to preserve prior evaluation')
 snapshots={path:path.read_bytes() for path in (DATASET,args.labels,args.predictions)}
 result=evaluate(strict_loads(snapshots[DATASET]),strict_loads(snapshots[args.labels]),strict_loads(snapshots[args.predictions]),DATASET.parent)
 result['inputSha256']={str(path.resolve()):hashlib.sha256(raw).hexdigest() for path,raw in snapshots.items()}
 args.output.parent.mkdir(parents=True,exist_ok=True)
 with args.output.open('x') as stream:stream.write(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
 print(json.dumps({k:result[k] for k in ('counts','metrics','majorityBaseline')},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
