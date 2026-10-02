"""Validate attempt-bound visual expert opinions and archive immutable imports."""
import argparse,copy,datetime,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
FIELDS={'attemptId','videoId','sourceSha256','lastContact','firstContact','rotationAssessment','visibility','notes','reviewedAt'}
def validate_review(payload,manifest):
    if not isinstance(payload,dict) or payload.get('schemaVersion')!=1 or payload.get('kind')!='rotation-expert-review':raise ValueError('Unsupported rotation review format')
    records=payload.get('assessments')
    if not isinstance(records,list):raise ValueError('Assessments must be a list')
    items={i['attemptId']:i for i in manifest['items']};seen=set()
    for row in records:
        if not isinstance(row,dict) or set(row)!=FIELDS:raise ValueError('Unexpected assessment fields')
        aid=row['attemptId']
        if not isinstance(aid,str) or aid in seen or aid not in items:raise ValueError('Unknown or duplicate attempt')
        seen.add(aid);item=items[aid]
        for key in ('sourceSha256','videoId','lastContact','firstContact'):
            if type(row[key]) is not type(item[key]) or row[key]!=item[key]:raise ValueError('Stale source or contact: '+key)
        if row['rotationAssessment'] not in ('unknown','apparently_complete','apparently_short'):raise ValueError('Invalid visual assessment')
        visibility=row['visibility']
        if not isinstance(visibility,dict) or set(visibility)!={'takeoff','landing'} or any(v not in ('clear','uncertain','not_visible') for v in visibility.values()):raise ValueError('Invalid visibility')
        if not isinstance(row['notes'],str) or len(row['notes'])>5000:raise ValueError('Invalid notes')
        try:
            stamp=datetime.datetime.fromisoformat(row['reviewedAt'].replace('Z','+00:00'))
            if stamp.tzinfo is None:raise ValueError('Timestamp needs timezone')
        except (ValueError,TypeError,AttributeError):raise ValueError('Invalid review timestamp') from None
    return copy.deepcopy(payload)
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('input',type=Path);parser.add_argument('--validate-only',action='store_true');args=parser.parse_args()
    manifest=json.loads((ROOT/'data/axel-demo-v1/rotation-review-data.json').read_text())
    payload=validate_review(json.loads(args.input.read_text()),manifest)
    canonical=json.dumps(payload,ensure_ascii=False,sort_keys=True,indent=2)+'\n'
    digest=hashlib.sha256(canonical.encode()).hexdigest()
    if args.validate_only:print('Valid:',len(payload['assessments']),'attempt-linked expert opinions');return
    dest=ROOT/'data/rotation-expert-v1/imports';dest.mkdir(parents=True,exist_ok=True);path=dest/(digest+'.json')
    if path.exists() and path.read_text()!=canonical:raise ValueError('Existing import checksum mismatch')
    if not path.exists():path.write_text(canonical)
    print('Archived:',path,'; assessments:',len(payload['assessments']))
if __name__=='__main__':main()
