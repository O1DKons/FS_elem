import { mergeAssessments, validateManifest, makeAssessment, restoreAssessments, exportAssessments } from './rotation-review-core.mjs';
const $ = id => document.getElementById(id);
const storageKey = 'fs-elem.rotation-expert-review.v1';
let manifest, current = 0, position = 0, timer = null, generation = 0, dirty = false, persistenceFailed = false;
const saved = new Map(), drafts = new Map();
const context = $('frame').getContext('2d');
function status(text, error = false) { $('status').textContent = text; $('status').classList.toggle('error', error); }
const item = () => manifest.items[current];
function draft() { return { rotationAssessment: $('assessment').value, visibility: { takeoff: $('takeoff-visibility').value, landing: $('landing-visibility').value }, notes: $('notes').value }; }
function stop() { clearInterval(timer); timer = null; $('play').textContent = '▶ 10 кадров/с'; }
function draw() {
  const token = ++generation, frame = item().frames[position];
  context.fillStyle = '#06080d'; context.fillRect(0, 0, 1280, 720);
  $('frame-info').textContent = `Кадр ${frame.frameIndex} · ${frame.time.toFixed(3)} с · ${position + 1} / ${item().frames.length}`;
  $('timeline').value = position; $('previous').disabled = position === 0; $('next').disabled = position === item().frames.length - 1;
  const image = new Image();
  image.onload = () => { if (token !== generation) return; context.drawImage(image, 0, 0, 1280, 720); };
  image.onerror = () => { if (token !== generation) return; stop(); status(`Не удалось загрузить кадр ${frame.frameIndex}. Оценку по этому кадру не делайте.`, true); };
  image.src = frame.image;
}
function move(next) { position = Math.max(0, Math.min(item().frames.length - 1, next)); draw(); }
function stateText() { $('saved-state').textContent = dirty ? 'Есть изменения, ещё не сохранённые.' : saved.has(item().attemptId) ? (persistenceFailed ? 'Оценка только в памяти страницы — скачайте JSON.' : 'Оценка сохранена.') : 'Эта попытка ещё не оценена.'; $('progress').textContent = `Сохранено ${saved.size} из ${manifest.items.length}`; $('download').disabled = saved.size === 0; }
function selectAttempt(index) {
  stop(); if (manifest && $('workspace').hidden === false) { if (dirty) drafts.set(item().attemptId, draft()); else drafts.delete(item().attemptId); }
  current = index; position = 0;
  const active = item(), value = drafts.get(active.attemptId) || saved.get(active.attemptId) || { rotationAssessment: 'unknown', visibility: { takeoff: 'uncertain', landing: 'uncertain' }, notes: '' };
  $('athlete').textContent = `${active.athlete || active.videoId} · ${active.attemptId}`;
  $('assessment').value = value.rotationAssessment; $('takeoff-visibility').value = value.visibility.takeoff; $('landing-visibility').value = value.visibility.landing; $('notes').value = value.notes;
  $('timeline').max = active.frames.length - 1;
  dirty = drafts.has(active.attemptId) && JSON.stringify(value) !== JSON.stringify(saved.has(active.attemptId) ? { rotationAssessment: saved.get(active.attemptId).rotationAssessment, visibility: saved.get(active.attemptId).visibility, notes: saved.get(active.attemptId).notes } : { rotationAssessment: 'unknown', visibility: { takeoff: 'uncertain', landing: 'uncertain' }, notes: '' });
  for (const [id, key] of [['takeoff', 'lastContact'], ['landing', 'firstContact']]) $(id).disabled = !active.frames.some(f => f.frameIndex === active[key]);
  stateText(); draw();
}
$('attempt').addEventListener('change', event => selectAttempt(Number(event.target.value)));
$('previous').onclick = () => { stop(); move(position - 1); };
$('next').onclick = () => { stop(); move(position + 1); };
$('timeline').oninput = event => { stop(); move(Number(event.target.value)); };
$('play').onclick = () => { if (timer) return stop(); if (position === item().frames.length - 1) move(0); $('play').textContent = 'Ⅱ Пауза'; timer = setInterval(() => { if (position >= item().frames.length - 1) return stop(); move(position + 1); }, 100); };
for (const [id, key] of [['takeoff', 'lastContact'], ['landing', 'firstContact']]) $(id).onclick = () => { stop(); const index = item().frames.findIndex(f => f.frameIndex === item()[key]); if (index >= 0) move(index); };
$('review').oninput = () => { dirty = true; stateText(); };
$('review').onsubmit = event => {
  event.preventDefault();
  try {
    const record = makeAssessment(item(), draft()); saved.set(record.attemptId, record); drafts.delete(record.attemptId); dirty = false; stateText();
    try { localStorage.setItem(storageKey, JSON.stringify(exportAssessments([...saved.values()]))); persistenceFailed = false; stateText(); status('Оценка сохранена в этом браузере.'); }
    catch { persistenceFailed = true; stateText(); status('Память браузера недоступна. Оценка сохранена только до закрытия страницы — скачайте JSON сейчас.', true); }
  } catch (error) { status(error.message, true); }
};
$('download').onclick = () => { const url = URL.createObjectURL(new Blob([JSON.stringify(exportAssessments([...saved.values()]), null, 2)], { type: 'application/json' })); const a = document.createElement('a'); a.href = url; a.download = 'rotation-expert-review.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); };
document.addEventListener('keydown', event => { if (!manifest || /INPUT|TEXTAREA|SELECT|BUTTON/.test(event.target.tagName)) return; if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); stop(); move(position + (event.key === 'ArrowLeft' ? -1 : 1)); } });
window.addEventListener('beforeunload', event => { if (dirty || drafts.size || persistenceFailed) { event.preventDefault(); event.returnValue = ''; } });
try {
  const response = await fetch('rotation-review-data.json', { cache: 'no-store' }); if (!response.ok) throw new Error(`Набор кадров недоступен: ${response.status}`); manifest = validateManifest(await response.json());
  let storageFailed = false, importedFailed = false, importedText = null, localText = null;
  try {
    const imported = await fetch('rotation-review-saved.json', { cache: 'no-store' });
    if (imported.ok) importedText = await imported.text();
    else if (imported.status !== 404) importedFailed = true;
  } catch { importedFailed = true; }
  try { localText = localStorage.getItem(storageKey); } catch { storageFailed = true; }
  for (const record of mergeAssessments(importedText, localText, manifest)) saved.set(record.attemptId, record);
  manifest.items.forEach((entry, index) => { const option = document.createElement('option'); option.value = index; option.textContent = `${index + 1}. ${entry.athlete || entry.videoId} · ${entry.attemptId}`; $('attempt').append(option); });
  const requestedAttempt = new URLSearchParams(location.search).get('attempt');
  const requestedIndex = manifest.items.findIndex(entry => entry.attemptId === requestedAttempt);
  $('attempt').value = String(Math.max(0, requestedIndex));
  selectAttempt(Math.max(0, requestedIndex)); $('workspace').hidden = false;
  status(storageFailed ? 'Память браузера недоступна. После оценки скачайте JSON.' : importedFailed ? 'Архив оценок не загрузился. Показаны доступные ответы браузера; перед повторной разметкой перезагрузите страницу.' : 'Исходные кадры и сохранённые оценки готовы. Новые правки сохраняйте кнопкой ниже.', storageFailed || importedFailed);
} catch (error) { status(`Не удалось открыть проверку: ${error.message}`, true); }
