"""Build a blind, local full-program annotation page for one source video."""
import argparse
import hashlib
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def render_review(*, video_url, review_id, duration, fps, source_sha256):
    if not isinstance(video_url, str) or not video_url:
        raise ValueError("video_url is required")
    if not isinstance(review_id, str) or not review_id:
        raise ValueError("review_id is required")
    if not isinstance(duration, (int, float)) or duration <= 0:
        raise ValueError("duration must be positive")
    if not isinstance(fps, (int, float)) or fps <= 0:
        raise ValueError("fps must be positive")
    if not isinstance(source_sha256, str) or len(source_sha256) != 64:
        raise ValueError("source_sha256 must be a SHA-256 hex digest")
    try:
        int(source_sha256, 16)
    except ValueError as exc:
        raise ValueError("source_sha256 must be a SHA-256 hex digest") from exc

    config = json.dumps(
        {
            "reviewId": review_id,
            "duration": float(duration),
            "fps": float(fps),
            "sourceSha256": source_sha256,
        },
        ensure_ascii=True,
        separators=(",", ":"),
    ).replace("<", "\\u003c")
    safe_id = html.escape(review_id, quote=True)
    safe_video = html.escape(video_url, quote=True)
    display_fps = f"{fps:g}"
    return f'''<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Разметка полной программы · FS_elem</title>
  <style>
    :root {{ color-scheme: light; --ink:#162b3b; --muted:#587080; --paper:#f2f7f8; --white:#fff; --ice:#cfe7ed; --line:#bad0d8; --cyan:#007c91; --amber:#cf7818; --red:#a43832; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--paper); color:var(--ink); font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
    header {{ padding:22px clamp(18px,3vw,42px) 17px; border-bottom:1px solid var(--line); background:var(--white); display:flex; align-items:end; justify-content:space-between; gap:24px; }}
    h1 {{ font-size:clamp(22px,2.5vw,32px); line-height:1.1; margin:0 0 7px; letter-spacing:-.035em; }}
    header p {{ margin:0; color:var(--muted); }}
    .source {{ text-align:right; color:var(--muted); font-size:12px; overflow-wrap:anywhere; max-width:310px; }}
    main {{ display:grid; grid-template-columns:minmax(0,1.65fr) minmax(340px,.85fr); min-height:calc(100vh - 102px); }}
    .viewer {{ padding:24px clamp(18px,3vw,42px); min-width:0; }}
    .video-wrap {{ background:#07141c; border:1px solid #112e3b; }}
    video {{ display:block; width:100%; max-height:calc(100vh - 280px); min-height:240px; background:#07141c; }}
    .transport {{ display:flex; align-items:center; gap:8px; flex-wrap:wrap; padding:10px; background:#102938; color:#fff; }}
    button,select,input {{ font:inherit; }}
    button {{ border:1px solid var(--line); border-radius:4px; background:#fff; color:var(--ink); padding:8px 11px; cursor:pointer; }}
    button:hover {{ border-color:var(--cyan); }}
    button:focus-visible,input:focus-visible,select:focus-visible {{ outline:3px solid #edaa50; outline-offset:2px; }}
    .transport button {{ background:#183b4b; border-color:#416371; color:#fff; min-width:44px; }}
    .transport button:hover {{ background:#225467; }}
    .timecode {{ min-width:108px; padding:4px 8px; color:#f3b95d; font-variant-numeric:tabular-nums; font-weight:700; }}
    .seek {{ flex:1 1 180px; accent-color:#efad4b; }}
    .viewer-note {{ margin:13px 0 0; color:var(--muted); max-width:72ch; }}
    aside {{ border-left:1px solid var(--line); padding:24px; background:#e8f1f3; }}
    h2 {{ margin:0; font-size:20px; letter-spacing:-.02em; }}
    .aside-intro {{ color:var(--muted); margin:7px 0 18px; }}
    .field-label {{ display:block; font-weight:650; margin:11px 0 4px; }}
    .event-list {{ display:grid; gap:12px; }}
    .event {{ border-top:1px solid var(--line); padding:12px 0 2px; }}
    .event-head {{ display:flex; justify-content:space-between; align-items:center; gap:12px; }}
    .event-title {{ font-weight:700; }}
    .remove {{ border:0; color:var(--red); background:transparent; padding:4px; }}
    .event select,.event input[type=text] {{ width:100%; border:1px solid var(--line); background:#fff; border-radius:4px; padding:8px; color:var(--ink); }}
    .marks {{ display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-top:10px; }}
    .mark {{ display:grid; gap:4px; color:var(--muted); font-size:12px; }}
    .mark button {{ text-align:left; padding:7px; font-size:13px; }}
    .frame-value {{ font-variant-numeric:tabular-nums; color:var(--ink); font-weight:650; }}
    .actions {{ border-top:1px solid var(--line); margin-top:18px; padding-top:15px; display:grid; gap:9px; }}
    .primary {{ background:var(--cyan); color:white; border-color:var(--cyan); font-weight:700; }}
    .primary:hover {{ background:#005d70; color:#fff; }}
    .coverage {{ display:flex; gap:9px; align-items:start; font-size:13px; color:var(--muted); }}
    .coverage input {{ margin-top:4px; accent-color:var(--cyan); }}
    .status {{ min-height:20px; color:var(--muted); font-size:13px; }}
    .status.error {{ color:var(--red); }}
    .status.ok {{ color:#126f56; }}
    .micro {{ font-size:12px; color:var(--muted); margin:0; }}
    @media (max-width:850px) {{ main {{ grid-template-columns:1fr; }} aside {{ border-left:0; border-top:1px solid var(--line); }} video {{ max-height:58vh; }} header {{ align-items:start; flex-direction:column; }} .source {{ text-align:left; }} }}
    @media (prefers-reduced-motion:reduce) {{ *,*::before,*::after {{ scroll-behavior:auto !important; }} }}
  </style>
</head>
<body>
  <header>
    <div><h1>Просмотр полной программы</h1><p>Отметьте все прыжковые события по видео, не сверяясь с подсказками модели.</p></div>
    <div class="source">{safe_id}<br>{display_fps} fps · исходник SHA-256 {source_sha256[:12]}</div>
  </header>
  <main>
    <section class="viewer" aria-label="Видеопроигрыватель">
      <div class="video-wrap">
        <video id="video" controls playsinline preload="metadata" src="{safe_video}"></video>
        <div class="transport">
          <button type="button" id="step-back" aria-label="На один кадр назад">−1 кадр</button>
          <button type="button" id="step-forward" aria-label="На один кадр вперёд">+1 кадр</button>
          <span class="timecode" id="timecode">00:00.000</span>
          <input class="seek" id="seek" type="range" min="0" max="{float(duration):.6f}" step="0.02" value="0" aria-label="Позиция видео">
        </div>
      </div>
      <p class="viewer-note">Сначала просмотрите видео целиком. Отметьте все прыжки, не только аксели; каждый прыжок в комбинации отмечайте отдельно. Для каждого укажите последний кадр контакта перед отрывом и первый кадр касания при приземлении. Для акселя укажите тип и оценку вращения; для остальных выберите «Другой прыжок». Если тип прыжка неясен, выберите «Не уверен(а)» — не угадывайте.</p>
    </section>
    <aside>
      <h2>События программы</h2>
      <p class="aside-intro">Все прыжки нужны для подсчёта ложных срабатываний; разметки только акселей недостаточно. Отметки сохраняются в этом браузере; передайте JSON после экспорта.</p>
      <div id="events" class="event-list"></div>
      <div class="actions">
        <button type="button" id="add-event">Добавить прыжок</button>
        <label class="coverage"><input id="coverage-reviewed" type="checkbox"><span>Я просмотрел(а) всю программу и внёс(ла) все прыжковые события, которые смог(ла) определить.</span></label>
        <button type="button" id="export-json" class="primary">Скачать разметку JSON</button>
        <p class="micro">Экспорт содержит исходный SHA-256, частоту кадров и кадры контакта. Протокольные оценки и прогнозы модели в разметку не включаются.</p>
        <div id="status" class="status" role="status" aria-live="polite"></div>
      </div>
    </aside>
  </main>
  <script id="review-config" type="application/json">{config}</script>
  <script>
  (() => {{
    const cfg = JSON.parse(document.getElementById('review-config').textContent);
    const video = document.getElementById('video');
    const seek = document.getElementById('seek');
    const timecode = document.getElementById('timecode');
    const eventsNode = document.getElementById('events');
    const coverage = document.getElementById('coverage-reviewed');
    const status = document.getElementById('status');
    const storageKey = `fs-elem-blind-review:${{cfg.sourceSha256}}`;
    const pad = n => String(n).padStart(2, '0');
    const formatTime = value => {{
      const ms = Math.max(0, Math.round(value * 1000));
      const minutes = Math.floor(ms / 60000), seconds = Math.floor(ms / 1000) % 60;
      return `${{pad(minutes)}}:${{pad(seconds)}}.${{String(ms % 1000).padStart(3,'0')}}`;
    }};
    const currentFrame = () => Math.max(0, Math.round(video.currentTime * cfg.fps));
    const showTime = () => {{
      const t = video.currentTime || 0;
      timecode.textContent = `${{formatTime(t)}} · кадр ${{currentFrame()}}`;
      seek.value = String(t);
    }};
    const setStatus = (message, kind='') => {{ status.textContent = message; status.className = `status ${{kind}}`; }};
    video.addEventListener('timeupdate', showTime);
    video.addEventListener('seeked', showTime);
    seek.addEventListener('input', () => {{ video.currentTime = Number(seek.value); }});
    document.getElementById('step-back').addEventListener('click', () => {{ video.pause(); video.currentTime = Math.max(0, video.currentTime - 1 / cfg.fps); }});
    document.getElementById('step-forward').addEventListener('click', () => {{ video.pause(); video.currentTime = Math.min(cfg.duration, video.currentTime + 1 / cfg.fps); }});

    function readState() {{
      try {{ return JSON.parse(localStorage.getItem(storageKey) || '{{}}'); }} catch {{ return {{}}; }}
    }}
    function saveState() {{
      const data = {{coverageReviewed:coverage.checked,events:[...eventsNode.querySelectorAll('.event')].map(readEvent)}};
      localStorage.setItem(storageKey, JSON.stringify(data));
      setStatus('Черновик сохранён в этом браузере.','ok');
    }}
    function readEvent(node) {{
      const get = name => node.querySelector(`[name="${{name}}"]`);
      const number = name => {{ const field=get(name); return !field || field.value === '' ? null : Number(field.value); }};
      return {{
        id:node.dataset.id,
        eventClass:get('eventClass').value,
        elementCode:get('elementCode').value.trim(),
        rotationAssessment:get('rotationAssessment').value,
        lastContactFrame:number('lastContactFrame'),
        firstContactFrame:number('firstContactFrame'),
        note:get('note').value.trim()
      }};
    }}
    function updateRotationVisibility(node) {{
      const isAxel = node.querySelector('[name="eventClass"]').value === 'axel';
      node.querySelector('.rotation-field').hidden = !isAxel;
      if (!isAxel) node.querySelector('[name="rotationAssessment"]').value = 'not_applicable';
      else if (node.querySelector('[name="rotationAssessment"]').value === 'not_applicable') node.querySelector('[name="rotationAssessment"]').value = 'unclear';
    }}
    function makeEvent(value={{}}) {{
      const n = eventsNode.children.length + 1;
      const node = document.createElement('section'); node.className='event'; node.dataset.id=value.id || `event-${{crypto.randomUUID()}}`;
      node.innerHTML = `<div class="event-head"><span class="event-title">Прыжок ${{n}}</span><button type="button" class="remove">Удалить</button></div>
        <label class="field-label">Что произошло</label><select name="eventClass"><option value="" selected disabled>Выберите тип</option><option value="axel">Аксель</option><option value="other_jump">Другой прыжок</option><option value="uncertain">Не уверен(а)</option></select>
        <label class="field-label">Название элемента</label><input type="text" name="elementCode" maxlength="20" placeholder="Например, 2A или 2Lz">
        <label class="field-label rotation-field">Оценка вращения по видео</label><select class="rotation-field" name="rotationAssessment"><option value="unclear">Неясно</option><option value="apparently_complete">Выглядит докрученным</option><option value="apparently_short">Выглядит недокрученным</option></select>
        <div class="marks"><label class="mark">Последний контакт перед отрывом<span class="frame-value" data-frame="lastContactFrame">не отмечен</span><button type="button" data-mark="lastContactFrame">Взять текущий кадр</button></label>
        <label class="mark">Первое касание при приземлении<span class="frame-value" data-frame="firstContactFrame">не отмечен</span><button type="button" data-mark="firstContactFrame">Взять текущий кадр</button></label></div>
        <label class="field-label">Комментарий (необязательно)</label><input type="text" name="note" maxlength="300" placeholder="Что было видно или почему сомневаетесь">`;
      node.querySelector('[name="eventClass"]').value=value.eventClass || '';
      node.querySelector('[name="elementCode"]').value=value.elementCode || '';
      node.querySelector('[name="rotationAssessment"]').value=value.rotationAssessment || 'unclear';
      node.querySelector('[name="note"]').value=value.note || '';
      for (const key of ['lastContactFrame','firstContactFrame']) {{
        if (Number.isInteger(value[key])) node.querySelector(`[name="${{key}}"]`)?.setAttribute('value', String(value[key]));
        const button=node.querySelector(`[data-mark="${{key}}"]`);
        button.addEventListener('click', () => {{
          const frame=currentFrame();
          let input=node.querySelector(`[name="${{key}}"]`);
          if (!input) {{ input=document.createElement('input'); input.type='hidden'; input.name=key; node.append(input); }}
          input.value=String(frame); node.querySelector(`[data-frame="${{key}}"]`).textContent=`кадр ${{frame}} · ${{formatTime(frame/cfg.fps)}}`; saveState();
        }});
      }}
      for (const key of ['lastContactFrame','firstContactFrame']) {{
        if (Number.isInteger(value[key])) {{
          const input=document.createElement('input'); input.type='hidden'; input.name=key; input.value=String(value[key]); node.append(input);
          node.querySelector(`[data-frame="${{key}}"]`).textContent=`кадр ${{value[key]}} · ${{formatTime(value[key]/cfg.fps)}}`;
        }}
      }}
      node.querySelector('.remove').addEventListener('click', () => {{ node.remove(); [...eventsNode.children].forEach((e,i)=>e.querySelector('.event-title').textContent=`Прыжок ${{i+1}}`); saveState(); }});
      node.querySelector('[name="eventClass"]').addEventListener('change', () => {{ updateRotationVisibility(node); saveState(); }});
      node.querySelectorAll('select,input').forEach(input=>input.addEventListener('change',saveState));
      updateRotationVisibility(node); eventsNode.append(node); return node;
    }}
    document.getElementById('add-event').addEventListener('click', () => {{ makeEvent(); video.pause(); saveState(); }});
    video.addEventListener('error', () => setStatus('Не удалось загрузить видео. Проверьте локальный сервер и исходный файл.', 'error'));
    coverage.addEventListener('change',saveState);
    document.getElementById('export-json').addEventListener('click', () => {{
      const events=[...eventsNode.querySelectorAll('.event')].map(readEvent);
      if (!coverage.checked) return setStatus('Сначала подтвердите полный просмотр программы.', 'error');
      for (const [i,e] of events.entries()) {{
        if (!e.eventClass) return setStatus(`Выберите тип события у прыжка ${{i+1}}.`, 'error');
        if (!Number.isInteger(e.lastContactFrame) || !Number.isInteger(e.firstContactFrame) || e.firstContactFrame <= e.lastContactFrame) return setStatus(`Проверьте кадры контакта у прыжка ${{i+1}}.`, 'error');
        if (e.eventClass === 'axel' && (!e.elementCode || e.rotationAssessment === 'not_applicable')) return setStatus(`Укажите название акселя и оценку вращения у прыжка ${{i+1}}.`, 'error');
        if (e.lastContactFrame < 0 || e.firstContactFrame / cfg.fps > cfg.duration + 0.1) return setStatus(`Кадры прыжка ${{i+1}} выходят за границы исходника.`, 'error');
      }}
      const result={{schemaVersion:1,reviewId:cfg.reviewId,sourceSha256:cfg.sourceSha256,durationSeconds:cfg.duration,fps:cfg.fps,coverageReviewed:true,reviewedAt:new Date().toISOString(),events}};
      const blob=new Blob([JSON.stringify(result,null,2)+'\\n'],{{type:'application/json'}}); const url=URL.createObjectURL(blob); const a=document.createElement('a'); a.href=url; a.download=`${{cfg.reviewId}}-expert-review.json`; a.click(); URL.revokeObjectURL(url); setStatus('JSON сохранён. Передайте файл для проверки разметки.', 'ok');
    }});
    const old=readState(); coverage.checked=old.coverageReviewed===true; (old.events || []).forEach(makeEvent); showTime();
    if (old.events?.length) setStatus('Загружен локальный черновик.','ok');
  }})();
  </script>
</body>
</html>'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--review-id", required=True)
    parser.add_argument("--duration", required=True, type=float)
    parser.add_argument("--fps", required=True, type=float)
    parser.add_argument("--video-url", required=True)
    args = parser.parse_args()
    if not args.input.is_file():
        raise ValueError("Input video is missing")
    digest = hashlib.sha256(args.input.read_bytes()).hexdigest()
    result = render_review(
        video_url=args.video_url,
        review_id=args.review_id,
        duration=args.duration,
        fps=args.fps,
        source_sha256=digest,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result, encoding="utf-8")
    print(json.dumps({"review": str(args.output.resolve()), "sourceSha256": digest}))


if __name__ == "__main__":
    main()
