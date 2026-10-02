import type {Episode,EventName,BoundaryReview} from '@/lib/annotation-types';
import {EVENT_DEFINITIONS,uncertaintyInterval} from '../../../../shared/phase-events.mjs';
import {Button} from '@/components/ui/button';
export function EventEditor({episode,frames,onMark,disabled,patch,seek}:{episode:Episode;frames:number[];onMark:(key:EventName)=>void;disabled:boolean;patch:(data:Partial<Episode>)=>void;seek:(time:number)=>void}){
 function reviewControls(label:string,frame:number,review:BoundaryReview|undefined,update:(r:BoundaryReview)=>void){
  const value=review??{uncertaintyFrames:0,review:'unreviewed'};
  const range=uncertaintyInterval(frame,value.uncertaintyFrames,frames.length);
  return <div className="event-review"><label>± кадров <input aria-label={`Неопределённость: ${label}`} type="number" min={0} max={30} value={value.uncertaintyFrames} onChange={e=>{const n=Number(e.target.value);if(Number.isInteger(n)&&n>=0&&n<=30)update({...value,uncertaintyFrames:n,review:'unreviewed'})}}/></label><span>Диапазон: {range[0]+1}–{range[1]+1}</span><label><input type="checkbox" checked={value.review==='confirmed'} onChange={e=>update({...value,review:e.target.checked?'confirmed':'unreviewed'})}/> Проверено: {label}</label></div>;
 }
 return <section className="phase-editor" aria-label="События прыжка"><h2>События прыжка</h2><p>Отмечайте наблюдаемые события на текущем кадре. «Проверено» означает проверку кадра вручную, а не оценку качества прыжка. Номера кадров показаны с 1.</p>
 {(['start','end'] as const).map(key=>{const frame=episode[key+'Frame' as 'startFrame'|'endFrame'];const label=key==='start'?'Первый кадр полёта':'Приземление';return frame==null?null:<div className="phase-row" key={key}><strong>{label} · кадр {frame+1}</strong>{reviewControls(label,frame,episode.boundaryReview?.[key],r=>patch({boundaryReview:{...episode.boundaryReview,[key]:r}}))}</div>})}
 {EVENT_DEFINITIONS.map(def=>{const key=def.key as EventName,mark=episode.events?.[key];return <div className="phase-row" key={key}><div><strong>{def.label}</strong><small>{def.description}</small></div><div className="phase-actions"><Button variant="outline" disabled={disabled} onClick={()=>onMark(key)}>{mark?'Переставить':'Отметить'}: {def.label}</Button>{mark?<><Button variant="ghost" disabled={disabled} onClick={()=>seek(mark.time)}>Кадр {mark.frameIndex+1}</Button><Button variant="ghost" aria-label={`Удалить: ${def.label}`} onClick={()=>{const events={...episode.events};delete events[key];patch({events})}}>Удалить</Button></>:<span>Не отмечено</span>}</div>{mark?reviewControls(def.label,mark.frameIndex,mark,r=>patch({events:{...episode.events,[key]:{...mark,...r}}})):null}</div>})}
 </section>;
}
