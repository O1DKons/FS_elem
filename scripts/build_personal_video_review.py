"""Publish neutral verified personal clips; never derive truth from filenames."""
import hashlib,json,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
 inventory=ROOT/'work/personal-validation-intake/inventory.json';records=json.loads(inventory.read_text())['records']
 if len(records)!=51 or len({r['sha256'] for r in records})!=51:raise ValueError('Expected51 unique clips')
 target=ROOT/'data/axel-demo-v1/personal-video-review';(target/'media').mkdir(parents=True,exist_ok=True)
 rows=[]
 for index,r in enumerate(records):
  source=ROOT/r['file'];digest=sha(source)
  if digest!=r['sha256']:raise ValueError('Source clip changed')
  name=f'media/{index+1:02d}.mp4';destination=target/name
  if not destination.exists():shutil.copyfile(source,destination)
  if sha(destination)!=digest:raise ValueError('Neutral copy mismatch')
  rows.append(dict(id=digest,sha256=digest,file=name,collection=r['collection']))
 dataset=hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(',',':')).encode()).hexdigest()
 (target/'data.json').write_text(json.dumps(dict(schemaVersion=1,datasetSha256=dataset,items=rows),indent=2,ensure_ascii=False))
 for name in ('index.html','core.mjs','app.mjs'):shutil.copyfile(ROOT/'scripts/personal-video-review-assets'/name,target/name)
 print(json.dumps(dict(count=len(rows),datasetSha256=dataset,path=str(target))))
if __name__=='__main__':main()
