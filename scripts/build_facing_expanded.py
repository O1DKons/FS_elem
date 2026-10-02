"""Extend expert orientation review without modifying original diagnostic manifest."""
import json,hashlib,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
 dst=ROOT/'data/axel-demo-v1'
 manifest=json.loads((dst/'boot-workbench-data.json').read_text())
 source=ROOT/'data/facing-expert-v1/imports/66ca3bc604d30150240058357546ec0e80e1239c5d7ad579b9b6286f6c28a785/labels.json'
 seeds=json.loads(source.read_text())['labels'];frames=[]
 for item in manifest['items']:
  lookup={f['frameIndex']:f for f in item['frames']}
  for offset in [-8,-4,-1,0,4]:
   f=lookup[item['firstContact']+offset]
   if hashlib.sha256((dst/f['image']).read_bytes()).hexdigest()!=f['sourceFrameSha256']:raise ValueError('Stale image')
   frames.append(dict(attemptId=item['attemptId'],athlete=item['athlete'],frameIndex=f['frameIndex'],image=f['image'],offset=offset,sourceSha256=item['sourceSha256'],sourceFrameSha256=f['sourceFrameSha256']))
 (dst/'facing-review-expanded-data.json').write_text(json.dumps(dict(schemaVersion=1,frames=frames,seedLabels=seeds,seedSha256=hashlib.sha256(source.read_bytes()).hexdigest()),ensure_ascii=False))
 page=(ROOT/'scripts/facing-review-assets/facing-review.html').read_text()
 page=page.replace('35 кадров из семи ошибок — диагностическая подборка, не независимый тест точности.','115 кадров всех 23 попыток. Ваши 35 оценок перенесены; осталось 80 новых кадров. Это прежнее соревнование, не независимый тест.')
 (dst/'facing-review-expanded.html').write_text(page)
 for name in ['facing-core.mjs','facing-review.mjs']:shutil.copy2(ROOT/'scripts/facing-review-assets'/name,dst/name)
 print(len(frames),len(seeds))
if __name__=='__main__':main()
