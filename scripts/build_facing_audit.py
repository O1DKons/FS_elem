"""Source-frame audit for front/back observability. No inferred facing labels."""
import json,html,shutil,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
 manifest=json.loads((ROOT/'data/axel-demo-v1/boot-workbench-data.json').read_text())
 baseline=json.loads((ROOT/'work/step35-element-sign/results.json').read_text())
 ids={r['attemptId'] for r,p in zip(baseline['records'],baseline['predictions']) if r['truth']!=p}
 rows=[];review=[]
 for item in manifest['items']:
  if item['attemptId'] not in ids:continue
  frames={f['frameIndex']:f for f in item['frames']};cards=[]
  for offset in (-8,-4,-1,0,4):
   f=frames.get(item['firstContact']+offset)
   if f is None:continue
   path=ROOT/'data/axel-demo-v1'/f['image']
   if hashlib.sha256(path.read_bytes()).hexdigest()!=f['sourceFrameSha256']:raise ValueError('Stale source frame')
   review.append(dict(attemptId=item['attemptId'],athlete=item['athlete'],frameIndex=f['frameIndex'],sourceSha256=item['sourceSha256'],sourceFrameSha256=f['sourceFrameSha256'],image=f['image'],offset=offset))
   url='boot-workbench.html?attempt='+item['attemptId']+'&frame='+str(f['frameIndex'])+'&side=landing'
   cards.append('<figure><a href="'+url+'"><img loading="lazy" src="'+html.escape(f['image'],quote=True)+'"></a><figcaption>'+str(f['frameIndex'])+' / '+str(offset)+'</figcaption></figure>')
  rows.append('<section><h2>'+html.escape(item['athlete']+' '+item['attemptId'])+'</h2><div>'+''.join(cards)+'</div></section>')
 page='<meta charset="utf-8"><title>Facing observability audit</title><style>body{font:17px system-ui;background:#101923;color:#eef;margin:25px}div{display:flex;overflow:auto}figure{min-width:420px;margin:5px}img{width:420px}a{color:#8df}</style><h1>Facing observability audit</h1><p>Seven errors of the preserved boot baseline. Original frames at contact offsets -8,-4,-1,0,+4. No skeleton overlay, no automatic front/back labels. Open an image to inspect its source frame.</p><p>Check whether face/back and landing foot direction are actually visible. Unclear images cannot provide reliable facing ground truth.</p>'+''.join(rows)
 (ROOT/'data/axel-demo-v1/facing-audit.html').write_text(page)
 (ROOT/'data/axel-demo-v1/facing-review-data.json').write_text(json.dumps(dict(schemaVersion=1,frames=review),ensure_ascii=False))
 for name in ['facing-review.html','facing-review.mjs','facing-core.mjs']:
  shutil.copy2(ROOT/'scripts/facing-review-assets'/name,ROOT/'data/axel-demo-v1'/name)
 print('Prepared',len(rows),'attempts')
if __name__=='__main__':main()
