"""Build a read-only review queue beside the demo, without replacing model data."""
import json
import hashlib
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DEMO=ROOT/'data/axel-demo-v1'
SOURCE=ROOT/'data/pose-identity-pilot-v1'

def main():
    assets=ROOT/'scripts/identity-review-assets'
    status_path=assets/'status.json'
    if status_path.exists() and json.loads(status_path.read_text()).get('status')=='suspended':
        (DEMO/'identity-review.json').write_text(json.dumps(dict(status='suspended',episodes=[])))
        (DEMO/'identity.html').write_text((assets/'suspended.html').read_text())
        for name in ('index.html','rtmpose-results.html'):
            path=DEMO/name
            if path.exists():path.write_text(path.read_text().replace('Проверка коротких смен сторон →','Результат эксперимента со сторонами →'))
        print('Identity experiment suspended; no active proposals. Main poses unchanged.')
        return
    demo=json.loads((DEMO/'data.json').read_text())
    result=json.loads((SOURCE/'evaluation.json').read_text())
    clips={c['id']:c for c in demo['clips']}
    episodes=[]
    for p in result['proposals']:
        clip=clips[p['attemptId']]
        proposals=[p]  # Preview this hypothesis alone, without other overlapping regions.
        from pose_identity import apply
        frames=[dict(frameIndex=f['frameIndex'],time=f['time'],image=f['image'],landmarks=f['pose']['RTMPose'])
                for f in clip['frames'] if p['startFrame']-2<=f['frameIndex']<=p['endFrame']+2]
        changed={f['frameIndex']:f['landmarks'] for f in apply(frames,proposals)}
        boxes=json.loads((ROOT/'data/pose-rtmpose-pilot-v1'/(clip['id']+'.raw.json')).read_text())
        box_by_frame={f['frameIndex']:f['selectedBox'] for f in boxes}
        b=[box_by_frame[f['frameIndex']] for f in frames if box_by_frame[f['frameIndex']] is not None]
        if b:
            xmin=min(v[0] for v in b);ymin=min(v[1] for v in b);xmax=max(v[2] for v in b);ymax=max(v[3] for v in b)
            size=max(xmax-xmin,ymax-ymin)*1.2
            crop=[(xmin+xmax-size)/2,(ymin+ymax-size)/2,size,size]
        else:crop=[0,0,1280,720]
        episodes.append(dict(**p,athlete=clip['athlete'],crop=crop,frames=[dict(frameIndex=f['frameIndex'],time=f['time'],image=f['image'],raw=f['landmarks'],proposed=changed[f['frameIndex']]) for f in frames]))
    (DEMO/'identity-review.json').write_text(json.dumps(dict(episodes=episodes,config=result['config'],method=result['method']),ensure_ascii=False))
    assets=ROOT/'scripts/identity-review-assets'
    core=(assets/'core.mjs').read_text()
    (DEMO/'identity-core.mjs').write_text(core)
    core_hash=hashlib.sha256(core.encode()).hexdigest()[:12]
    app=(assets/'identity.mjs').read_text().replace("./identity-core.mjs", "./identity-core.mjs?v="+core_hash)
    (DEMO/'identity.mjs').write_text(app)
    app_hash=hashlib.sha256(app.encode()).hexdigest()[:12]
    baseline=result['models']['RTMPose']['meanPx'];candidate=result['models']['Temporal hypothesis']['meanPx']
    text=f"На {result['located']} размеченных точках исходная ошибка: {baseline:.1f} px; после предложений: {candidate:.1f} px. Эти шесть опорных кадров не подтверждают качество изменений между ними. Плавность сама по себе не является доказательством точности."
    page=(assets/'identity.html').read_text().replace('__REFERENCE_RESULT__',text).replace('src="identity.mjs"','src="identity.mjs?v='+app_hash+'"')
    (DEMO/'identity.html').write_text(page)
    for name in ('index.html','rtmpose-results.html'):
        path=DEMO/name;text=path.read_text()
        if 'identity.html' not in text:text=text.replace('<main>', '<main><p><a href="identity.html">Проверка коротких смен сторон →</a></p>',1)
        path.write_text(text)
    print(f'Built {len(episodes)} isolated hypotheses; main poses unchanged.')

if __name__=='__main__':main()
