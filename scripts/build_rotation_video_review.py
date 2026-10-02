"""Fixed source-diverse20 external2A clips for blind expert binary review."""
import hashlib,json,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
 source=ROOT/'data/skatingverse-pilot-v1';manifest=json.loads((source/'manifest.json').read_text())
 candidates=sorted([r for r in manifest['items'] if int(r['label'])==2],key=lambda r:r['sha256'])
 selected=[];groups=set()
 for r in candidates:
  if r['group'] not in groups:selected.append(r);groups.add(r['group'])
  if len(selected)==20:break
 for r in candidates:
  if len(selected)==20:break
  if r not in selected:selected.append(r)
 if len(selected)!=20:raise ValueError('Need20 clips')
 target=ROOT/'data/axel-demo-v1/rotation-video-review';target.mkdir(parents=True,exist_ok=True);(target/'media').mkdir(exist_ok=True)
 rows=[]
 for index,r in enumerate(selected):
  path=source/r['file'];digest=hashlib.sha256(path.read_bytes()).hexdigest()
  if digest!=r['sha256']:raise ValueError('Video changed')
  name=f'media/{index+1:02d}.mp4';destination=target/name
  if not destination.exists():shutil.copyfile(path,destination)
  if hashlib.sha256(destination.read_bytes()).hexdigest()!=digest:raise ValueError('Review copy changed')
  rows.append(dict(id=r['sha256'],sha256=digest,file=name,sourceFile=r['file'],sourceGroup=r['group']))
 dataset_sha=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()
 data=dict(schemaVersion=1,datasetSha256=dataset_sha,items=rows,scope='Blind external-video review for frozen pivot model; not used in binary training. Source-diverse prefixes, athlete identity unverified. Type model used these videos; binary model did not. Do not use expert labels to tune and report the same data as independent test.')
 (target/'data.json').write_text(json.dumps(data,ensure_ascii=False,indent=2))
 for name in ('index.html','core.mjs','app.mjs'):shutil.copyfile(ROOT/'scripts/rotation-video-review-assets'/name,target/name)
 print(dataset_sha)
if __name__=='__main__':main()
