import {phaseEventError} from '../shared/phase-events.mjs';
export function invalid(message) { const e = Error(message); e.status = 400; return e; }
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
export function validateEpisode(e, catalog, framesByVideo) {
  if(!object(e)) throw invalid('Неверный эпизод');
  const video = catalog.find(v => v.id === e.videoId);
  if(!video || typeof e.id !== 'string' || !e.id.trim() || e.id.length > 100) throw invalid('Неизвестный ролик или эпизод');
  if(typeof e.attemptGroup !== 'string' || e.attemptGroup.length > 200) throw invalid('Неверная группа повторов');
  if(typeof e.note !== 'string' || e.note.length > 5000) throw invalid('Неверный комментарий');
  const times = framesByVideo[e.videoId];
  if(!Array.isArray(times) || !times.length) throw invalid('Нет временной шкалы видео');
  for(const name of ['start','end']) {
    const seconds = e[name], frame = e[name+'Frame'];
    if(seconds === null) {
      if(frame != null) throw invalid('Кадр без временной отметки');
    } else {
      if(!Number.isFinite(seconds) || seconds < 0 || seconds > Math.max(video.duration,times.at(-1))) throw invalid('Отметка вне видео');
      if(!Number.isSafeInteger(frame) || frame < 0 || frame >= times.length) throw invalid('Кадр вне видео');
      if(Math.abs(times[frame] - seconds) > 0.00002) throw invalid('Время не соответствует кадру');
    }
  }
  if(e.start !== null && e.end !== null && (e.end <= e.start || e.endFrame <= e.startFrame)) throw invalid('Конец должен быть позже начала');
  const eventError=phaseEventError(e,times);
  if(eventError)throw invalid(eventError);
  return true;
}
export function validateDocument(body, catalog, framesByVideo) {
  if(!object(body) || !Number.isSafeInteger(body.revision) || body.revision < 0) throw invalid('Неверная ревизия');
  if(body.capabilities!==undefined && (!Array.isArray(body.capabilities) || !body.capabilities.every(x=>typeof x==='string'))) throw invalid('Неверная версия возможностей редактора');
  if(body.schemaVersion !== undefined && ![1,2].includes(body.schemaVersion)) throw invalid('Неизвестная версия схемы');
  if(!Array.isArray(body.episodes) || body.episodes.length > 5000) throw invalid('Неверный список эпизодов');
  const ids = new Set();
  for(const e of body.episodes) {
    validateEpisode(e,catalog,framesByVideo);
    if(ids.has(e.id)) throw invalid('Повтор ID');
    ids.add(e.id);
  }
  return true;
}
export function validateCatalog(catalog, frames) {
  if(!Array.isArray(catalog) || !catalog.length) throw invalid('Пустой каталог');
  const ids = new Set();
  for(const v of catalog) {
    if(!object(v) || typeof v.id !== 'string' || !/^[a-zA-Z0-9_-]+$/.test(v.id) || ids.has(v.id.toLowerCase())) throw invalid('Неверный или повторный ID видео');
    ids.add(v.id.toLowerCase());
    if(!Number.isFinite(v.duration) || v.duration <= 0) throw invalid('Неверная длительность');
    const t = frames[v.id];
    if(!Array.isArray(t) || !t.length || t.some((x,i)=> !Number.isFinite(x) || x<0 || x>v.duration+0.01 || (i>0 && x<=t[i-1]))) throw invalid('Неверная временная шкала');
    if(v.frameCount !== undefined && v.frameCount !== t.length) throw invalid('Число кадров не совпадает');
  }
}
