"""Publish original-image rotation review, hiding protocol labels from reviewers."""
import hashlib,json,os,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    demo=ROOT/'data/axel-demo-v1';inputs=ROOT/'data/axel-boundaries-v1/manifest.json'
    items=[]
    for row in json.loads(inputs.read_text())['items']:
        aid=row['attemptId'];pose=json.loads((ROOT/'data/pose-batch-v1'/f'{aid}.json').read_text())
        if pose['sourceSha256']!=row['sourceSha256']:raise ValueError('Mismatched source: '+aid)
        frames=[];dest=demo/'rotation-frames'/aid;dest.mkdir(parents=True,exist_ok=True)
        for f in pose['frames']:
            n=f['frameIndex'];src=ROOT/'work/step6-pose'/aid/f'{n:06d}.png';target=dest/f'{n}.png'
            digest=sha(src)
            if not target.exists():
                try:os.link(src,target)
                except OSError:shutil.copyfile(src,target)
            if sha(target)!=digest:raise ValueError('Mismatched published frame')
            frames.append(dict(frameIndex=n,time=f['time'],image=f'rotation-frames/{aid}/{n}.png',sourceFrameSha256=digest))
        if any(b['frameIndex'] not in {f['frameIndex'] for f in frames} for k,b in row['boundaries'].items() if k in ('lastContact','firstContact')):raise ValueError('Missing contact frame')
        items.append(dict(attemptId=aid,athlete=row['athleteGroup'],videoId=row['videoId'],sourceSha256=row['sourceSha256'],lastContact=row['boundaries']['lastContact']['frameIndex'],firstContact=row['boundaries']['firstContact']['frameIndex'],frames=frames))
    manifest=dict(schemaVersion=1,fps=50,width=1280,height=720,items=items)
    (demo/'rotation-review-data.json').write_text(json.dumps(manifest,ensure_ascii=False))
    assets=ROOT/'scripts/rotation-review-assets'
    for src in assets.iterdir():
        if src.suffix in ('.html','.mjs','.css'):shutil.copyfile(src,demo/src.name)
    # Version all entry dependencies so previous app tabs cannot keep stale modules.
    core=demo/'rotation-review-core.mjs';module=demo/'rotation-review.mjs';page=demo/'rotation-review.html'
    if core.exists() and module.exists():
        module.write_text(module.read_text().replace("'./rotation-review-core.mjs'",f"'./rotation-review-core.mjs?v={sha(core)[:12]}'"))
        page.write_text(page.read_text().replace('rotation-review.mjs"',f'rotation-review.mjs?v={sha(module)[:12]}"').replace('rotation-review.css"',f'rotation-review.css?v={sha(demo/"rotation-review.css")[:12]}"'))
    for name in ('index.html','compare.html'):
        p=demo/name;s=p.read_text()
        if 'href="rotation-review.html"' not in s:s=s.replace('<main>','<main><p><a href="rotation-review.html">Разметка докрута: 23 попытки без подсказок протокола →</a></p>')
        p.write_text(s)
    print(f'Published {len(items)} attempts, {sum(len(i["frames"]) for i in items)} original PNG frames')
if __name__=='__main__':main()
