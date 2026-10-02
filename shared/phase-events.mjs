export const EVENT_DEFINITIONS = Object.freeze([
  {key:'lastContact',label:'Последний контакт',description:'Последний кадр с опорой на лёд перед полётом.'},
  {key:'groupingStart',label:'Начало группировки',description:'Начало сближения рук и ног с осью тела.'},
  {key:'groupingComplete',label:'Группировка собрана',description:'Первый кадр выбранного компактного положения.'},
  {key:'opening',label:'Начало раскрытия',description:'Начало раскрытия перед приземлением.'},
  {key:'exitStable',label:'Устойчивый выезд',description:'Первый кадр устойчивого выезда после касания.'},
]);
const isObject=v=>v!==null && typeof v==='object' && !Array.isArray(v);
const validReview=m=>Number.isInteger(m.uncertaintyFrames) && m.uncertaintyFrames>=0 && m.uncertaintyFrames<=30 && ['unreviewed','confirmed'].includes(m.review);
/** Shared by API and editor; returns a user-facing error without mutating input.
 * @param {any} episode @param {number[]} times @returns {string|null}
 */
export function phaseEventError(episode,times) {
  const events=episode.events;
  if(events!==undefined) {
    if(!isObject(events))return 'Неверный список событий прыжка.';
    for(const [key,mark] of Object.entries(events)) {
      const definition=EVENT_DEFINITIONS.find(d=>d.key===key);
      if(!definition)return 'Неизвестное событие прыжка.';
      if(!isObject(mark) || !Number.isSafeInteger(mark.frameIndex) || mark.frameIndex<0 || mark.frameIndex>=times.length || !Number.isFinite(mark.time) || Math.abs(mark.time-times[mark.frameIndex])>0.00002)
        return `${definition.label}: время должно соответствовать существующему кадру.`;
      if(mark.source!=='manual' || !validReview(mark))return `${definition.label}: нужна ручная отметка и неопределённость от 0 до 30 кадров.`;
    }
    if(events.lastContact && episode.startFrame!=null && events.lastContact.frameIndex>=episode.startFrame)return 'Последний контакт должен быть раньше первого кадра полёта.';
    const sequence=[['groupingStart','Начало группировки'],['groupingComplete','Собранная группировка'],['opening','Раскрытие']]
      .filter(([key])=>events[key]).map(([key,label])=>({frame:events[key].frameIndex,label}));
    if(episode.endFrame!=null)sequence.push({frame:episode.endFrame,label:'Приземление'});
    for(let i=1;i<sequence.length;i++)if(sequence[i-1].frame>sequence[i].frame)return `${sequence[i-1].label} не может быть позже: ${sequence[i].label.toLowerCase()}.`;
    if(events.exitStable && episode.endFrame!=null && events.exitStable.frameIndex<episode.endFrame)return 'Устойчивый выезд должен быть не раньше приземления.';
  }
  if(episode.boundaryReview!==undefined) {
    if(!isObject(episode.boundaryReview))return 'Неверная проверка границ.';
    for(const [key,review] of Object.entries(episode.boundaryReview)) {
      if(!['start','end'].includes(key) || episode[key]==null || !isObject(review) || !validReview(review))return 'Проверка границы требует отметку и неопределённость от 0 до 30 кадров.';
    }
  }
  return null;
}
/** @param {number} frame @param {number} uncertainty @param {number} length */
export function uncertaintyInterval(frame,uncertainty,length) {
  return [Math.max(0,frame-uncertainty),Math.min(length-1,frame+uncertainty)];
}
