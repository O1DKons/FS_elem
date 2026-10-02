"""Publish isolated feet workbench; preserve the existing viewer's core.mjs."""
import argparse,json,shutil,hashlib
from pathlib import Path
from boot_detection import candidates, temporal_checks, landing_candidates
ROOT=Path(__file__).resolve().parents[1]
ASSETS=('boot-workbench.html','boot-workbench.css','boot-workbench.mjs','boot-workbench-core.mjs')
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--partial',action='store_true',help='Development preview from completed cached clips');args=parser.parse_args()
 dst=ROOT/'data/axel-demo-v1';cache=ROOT/'data/boot-rtmw-v1';manifest=json.loads((dst/'rotation-review-data.json').read_text());result=[];weight_hashes=set()
 for item in manifest['items']:
  path=cache/f'{item["attemptId"]}.raw.json'
  if not path.exists():
   if args.partial:continue
   raise ValueError('Missing processed attempt '+item['attemptId'])
  raw=json.loads(path.read_text());frames=[];coords=[]
  weight_hashes.add(raw['weightsSha256'])
  pose_path=ROOT/'data/pose-batch-v1'/f'{item["attemptId"]}.json'
  if hashlib.sha256(pose_path.read_bytes()).hexdigest()!=raw['poseSha256']:raise ValueError('Stale pose bounding-box cache')
  for f in item['frames']:
   row=raw['frames'].get(str(f['frameIndex']))
   if not row or row['sourceFrameSha256']!=f['sourceFrameSha256']:raise ValueError('Incomplete/stale cache')
   pred=[] if row.get('missing') else candidates(row['points'],row['scores'],row['mirrored'],row['mirrorScores'],1280,720,row['bodyHeight'])
   frames.append(dict(frameIndex=f['frameIndex'],image=f['image'],sourceFrameSha256=f['sourceFrameSha256'],candidates=pred))
   for c in pred:
    if c['status']=='visible':coords.extend([c['toe'],c['heel']])
  frames=landing_candidates(temporal_checks(frames),item['firstContact'])
  if coords:
   x0=max(0,min(p[0] for p in coords)-60);x1=min(1280,max(p[0] for p in coords)+60);y0=max(0,min(p[1] for p in coords)-80);y1=min(720,max(p[1] for p in coords)+60)
   crop=[int(x0),int(y0),int(x1),int(y1)]
  else:crop=[0,0,1280,720]
  result.append({**{k:item[k] for k in ('attemptId','athlete','sourceSha256','firstContact','lastContact')},'frames':frames,'crop':crop})
 settings=json.loads((cache/'settings.json').read_text()) if (cache/'settings.json').exists() else {'status':'development_preview'}
 if len(weight_hashes)!=1 or (settings.get('weightsSha256') and settings['weightsSha256'] not in weight_hashes):raise ValueError('Mixed model weights in cache')
 settings.update(qualityLogicSha256=hashlib.sha256((ROOT/'scripts/boot_detection.py').read_bytes()).hexdigest(),temporalGate='Adjacent heading change >100deg or cheaper opposite-side assignment => uncertain; no coordinate smoothing or side swapping',landingCandidate='Lower image-y skate from manual firstContact-2 onward; height-gap and motion gates; not contact detection or anatomical identity ground truth')
 payload=dict(schemaVersion=1,model='RTMW-x · повторное определение стоп + зеркальная проверка',width=1280,height=720,fps=50,settings=settings,items=result)
 temp=dst/'boot-workbench-data.tmp';temp.write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False));temp.replace(dst/'boot-workbench-data.json')
 for asset in ASSETS:shutil.copy2(ROOT/'scripts/boot-workbench-assets'/asset,dst/asset)
 if not args.partial:
  index=dst/'index.html';text=index.read_text()
  if 'boot-workbench.html' not in text:
   backup=ROOT/'data/backups/pre-boot-workbench';backup.mkdir(parents=True,exist_ok=True)
   if not (backup/'index.html').exists():shutil.copy2(index,backup/'index.html')
   text=text.replace('<main>','<main><p><a href="boot-workbench.html">Коньки: автоматические ориентиры и покадровая проверка →</a></p>',1);index.write_text(text)
 print('Published',len(result),'attempts',sum(len(i['frames']) for i in result),'frames; core.mjs preserved')
if __name__=='__main__':main()
