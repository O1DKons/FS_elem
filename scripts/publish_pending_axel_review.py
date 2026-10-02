"""Show only unresolved development cards; never synthesize user answers."""
import html
import json
from pathlib import Path

from pose_cache_contract import sha

ROOT = Path(__file__).resolve().parents[1]


def pending_items(manifest, reconciliation):
    items = {row['id']: row for row in manifest['items']}
    known = {row['id']: row for row in reconciliation['alreadyKnownFromExactEventReviews']}
    pending = {row['id']: row for row in reconciliation['pendingExactCandidateAnswers']}
    if set(known) & set(pending) or set(known) | set(pending) != set(items):
        raise ValueError('Incomplete/overlapping reconciliation')
    for key, row in {**known, **pending}.items():
        if row['sourceSha256'] != items[key]['sourceSha256']:
            raise ValueError('Reconciliation source mismatch')
    return [row for row in manifest['items'] if row['id'] in pending], known


def publish():
    destination = ROOT / 'data/axel-demo-v1/personal-unified-review-v1'
    manifest_path = destination / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    reconcile_path = ROOT / 'work/personal-unified-review-v1/remaining-review-reconciliation-v1.json'
    reconciliation = json.loads(reconcile_path.read_text())
    if sha(manifest_path) != reconciliation['manifestSha256']:
        raise ValueError('Review manifest changed')
    pending, known = pending_items(manifest, reconciliation)
    for row in manifest['items']:
        if sha(destination / row['file']) != row['clipSha256']:
            raise ValueError('Review clip changed')
    for row in known.values():
        review = json.loads((ROOT / row['canonicalReview']).read_text())
        event = next(event for event in review['events'] if event['id'] == row['eventId'])
        if review['videoId'] != row['sourceSha256'] or not event['elementCode'].startswith(row['label']):
            raise ValueError('Known answer/canonical event mismatch')
    flagged = {row['id'] for row in reconciliation['knownOtherOverlapFlags']}
    cards = []
    for row in pending:
        number = int(row['id'].rsplit('-', 1)[1])
        flag = '<p class="warning">Этот интервал пересекается с ранее отмеченным другим прыжком. Проверьте именно показанный фрагмент.</p>' if row['id'] in flagged else ''
        cards.append(f'''<section id="{row['id']}"><h2>№{number} · {html.escape(row['athlete'])}</h2>
<p>Интервал в исходном видео: {row['sourceStart']:.2f}–{row['sourceEnd']:.2f} с.</p>{flag}
<video controls preload="none" src="{row['file']}"></video>
<label>Ваша оценка <select data-id="{row['id']}"><option value="">Не проверено</option>
<option>1A</option><option>2A</option><option value="other">Не аксель</option><option value="uncertain">Неясно</option></select></label>
<label>Комментарий <input data-note="{row['id']}" placeholder="Если видны два прыжка или есть сомнение"></label></section>''')
    known_text = ', '.join('№' + key.rsplit('-', 1)[1] + ' — ' + row['label'] for key, row in known.items())
    payload = json.dumps(manifest, ensure_ascii=False).replace('<', '\\u003c')
    pending_ids = json.dumps([row['id'] for row in pending])
    page = '''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>FS_elem — оставшиеся оценки</title><style>
body{background:#121821;color:#edf1f7;font:17px system-ui;max-width:1000px;margin:auto;padding:24px}
section{background:#1e2938;border-radius:12px;padding:20px;margin:24px 0}video{display:block;width:100%;max-height:520px;background:#000;margin:16px 0}
label{display:block;margin:12px 0}button,select,input{font:inherit;padding:10px}input{width:95%;box-sizing:border-box}
header{position:sticky;top:0;background:#121821;padding:12px 0;z-index:2}.warning{color:#f7cb87}button{cursor:pointer}
</style><header><strong>Осталось 14 фрагментов</strong> <button id="export">Скачать новые ответы JSON</button> <span id="count"></span></header>
<h1>Аксель и число оборотов</h1><p>Просмотрите заход и прыжок. Выберите 1A, 2A, «не аксель» или «неясно». Докрут сейчас не оценивается. Исходные номера карточек сохранены.</p>
<details><summary>Шесть оценок уже сохранены — повторять не нужно</summary><p>KNOWN_TEXT</p><p>Они взяты из точных экспертных событий. Эта страница не экспортирует их как новые ответы.</p></details>
<p>Новые ответы сохраняются в этом браузере. После проверки скачайте JSON и передайте его в чат.</p>CARDS
<script>const manifest=PAYLOAD;const pendingIds=PENDING_IDS;const storageKey=manifest.reviewId+':pending-only-v1';
let stored={};try{stored=JSON.parse(localStorage.getItem(storageKey)||'{}')}catch{}
let answers=Object.fromEntries(Object.entries(stored).filter(([id,value])=>pendingIds.includes(id)&&value&&typeof value==='object'));
function update(){document.querySelector('#count').textContent=Object.values(answers).filter(value=>value.label).length+' / '+pendingIds.length;localStorage.setItem(storageKey,JSON.stringify(answers))}
document.querySelectorAll('select').forEach(el=>{el.value=answers[el.dataset.id]?.label||'';el.onchange=()=>{answers[el.dataset.id]={...answers[el.dataset.id],label:el.value};update()}});
document.querySelectorAll('input').forEach(el=>{el.value=answers[el.dataset.note]?.note||'';el.oninput=()=>{answers[el.dataset.note]={...answers[el.dataset.note],note:el.value};update()}});
document.querySelector('#export').onclick=()=>{const data={...manifest,reviewedAt:new Date().toISOString(),answers};const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const anchor=document.createElement('a');anchor.href=url;anchor.download='personal-unified-expert-review.json';anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};update();</script></html>'''
    page = page.replace('KNOWN_TEXT', html.escape(known_text)).replace('CARDS', ''.join(cards)).replace('PAYLOAD', payload).replace('PENDING_IDS', pending_ids)
    (destination / 'remaining.html').write_text(page)
    result = {'pendingCards': len(pending), 'knownCardsNotRequestedAgain': len(known),
              'manifestSha256': sha(manifest_path), 'reconciliationSha256': sha(reconcile_path),
              'pageSha256': sha(destination / 'remaining.html'), 'all20ClipHashesVerified': True,
              'newExpertAnswersCreated': False, 'fullProgramCoverageInferred': False}
    output = ROOT / 'work/axel-corpus-review-v1'
    output.mkdir(exist_ok=True)
    (output / 'pending-page-verification.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    publish()
