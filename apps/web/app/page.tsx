'use client';
import {useEffect,useRef,useState} from 'react';
import {observeVideoReadiness} from '@/lib/video-readiness.mjs';
import {Button} from '@/components/ui/button';
import {Slider} from '@/components/ui/slider';
import {Select,SelectTrigger,SelectValue,SelectContent,SelectItem} from '@/components/ui/select';
import {Play,Pause,ChevronLeft,ChevronRight,Plus,Download,Check,Flag} from 'lucide-react';
import type {Episode,EventName} from '@/lib/annotation-types';
import {useAnnotations,annotationClient} from '@/hooks/useAnnotations';
import {VideoLibrary} from '@/components/editor/VideoLibrary';
import {EpisodePanel} from '@/components/editor/EpisodePanel';
import {EventEditor} from '@/components/editor/EventEditor';
import {phaseEventError} from '../../../shared/phase-events.mjs';
import {markBoundary,markEvent} from '../../../shared/event-editing.mjs';
import {isAxelDraft,axelReviewVideos} from '../../../shared/axel-review.mjs';
const time=(x:number|null)=>x===null?'—':`${Math.floor(x/60).toString().padStart(2,'0')}:${(x%60).toFixed(3).padStart(6,'0')}`;
export default function Home({axelOnly=false}:{axelOnly?:boolean}){
 const {videos,episodes,loaded,dirty,saving,failed,error,setError,undo,undoChange,current,revision,change,retry,status}=useAnnotations();
 const [vid,setVid]=useState(axelOnly?'comp-01':'01'),[active,setActive]=useState('');
 const [t,setT]=useState(0),[playing,setPlaying]=useState(false),[rate,setRate]=useState('0.25'),[frames,setFrames]=useState<number[]>([]),[ready,setReady]=useState(false),[seeking,setSeeking]=useState(false);
 const player=useRef<HTMLVideoElement>(null),loopEnd=useRef<number|null>(null);
 useEffect(()=>{
 const context=(document as Document & {modelContext?:{registerTool:(tool:unknown,options:unknown)=>unknown}}).modelContext;
 if(!context?.registerTool)return;const lifecycle=new AbortController();
 try{Promise.resolve(context.registerTool({name:'read_saved_jump_annotations',description:'Read jump annotations saved on this computer. Does not alter boundaries.',inputSchema:{type:'object',properties:{},additionalProperties:false},annotations:{readOnlyHint:true,untrustedContentHint:true},async execute(){return annotationClient.annotations();}},{signal:lifecycle.signal})).catch(()=>{});}catch{}
 return()=>lifecycle.abort();
 },[]);
 const shownVideos=axelOnly?axelReviewVideos(videos,episodes):videos;
 const video=videos.find(v=>v.id===vid),episode=episodes.find(e=>e.id===active),list=episodes.filter(e=>e.videoId===vid&&(!axelOnly||isAxelDraft(e)));
 useEffect(()=>{if(axelOnly&&!active){const first=episodes.find(e=>e.videoId===vid&&isAxelDraft(e));if(first)setActive(first.id)}},[axelOnly,active,episodes,vid]);
 const frameIndex=(x:number)=>{let l=0,r=frames.length-1;while(l<=r){let m=(l+r)>>1;if(frames[m]<=x+0.00001)l=m+1;else r=m-1;}return Math.max(0,r);};
 useEffect(()=>{setReady(false);setSeeking(false);setFrames([]);setT(0);setPlaying(false);loopEnd.current=null;let cancelled=false;annotationClient.frames(vid).then(a=>{if(!cancelled)setFrames(a)}).catch(e=>{if(!cancelled)setError(e.message)});return()=>{cancelled=true};},[vid]);
 useEffect(()=>{const p=player.current;if(p)return observeVideoReadiness(p,setReady)},[vid]);
 useEffect(()=>{const p=player.current;if(p)p.playbackRate=Number(rate)},[rate,vid,ready]);
 function patch(data:Partial<Episode>){if(!episode)return;const next={...episode,...data};const issue=phaseEventError(next,frames);if(issue){setError(issue);return;}setError('');change(current.current.map(e=>e.id===active?next:e));}
 function seek(x:number){const p=player.current;if(!p||!ready)return;p.pause();setPlaying(false);loopEnd.current=null;const next=Math.min(Math.max(0,x),Math.max(0,(p.duration||video?.duration||0)-0.001));p.currentTime=next;setT(next);}
 function step(n:number){if(!ready||seeking||!frames.length)return;const i=Math.min(frames.length-1,Math.max(0,frameIndex(player.current?.currentTime||0)+n));seek(frames[i]+((frames[i+1]??(frames[i]+0.01))-frames[i])*0.25);}
 function add(){const e:Episode={id:crypto.randomUUID(),videoId:vid,start:null,end:null,note:'',attemptGroup:''};change([...current.current,e]);setActive(e.id);}
 function mark(which:'start'|'end'){
  if(!loaded||!ready||seeking||!frames.length)return;const p=player.current!;p.pause();const i=frameIndex(p.currentTime),x=frames[i];
  if(episode&&((which==='start'&&episode.end!==null&&x>=episode.end)||(which==='end'&&episode.start!==null&&x<=episode.start))){setError('Конец должен быть позже начала. Переместитесь к нужному кадру.');return;}
  setError('');const values=which==='start'?{start:x,startFrame:i}:{end:x,endFrame:i};
  if(!episode){const e:Episode={id:crypto.randomUUID(),videoId:vid,start:null,end:null,note:'',attemptGroup:'',...values};change([...current.current,e]);setActive(e.id);}else patch(markBoundary(episode,which,i,frames));
 }
 function markPhase(key:EventName){const p=player.current;if(!episode||!p||!loaded||!ready||seeking||!frames.length)return;p.pause();loopEnd.current=null;setPlaying(false);setT(p.currentTime);patch(markEvent(episode,key,frameIndex(p.currentTime),frames));}
 function toggle(){const p=player.current;if(!p||!ready)return;if(p.paused)p.play().catch(()=>setError('Не удалось воспроизвести видео'));else p.pause();}
 function preview(){if(!episode||episode.start===null||episode.end===null)return;const p=player.current!;p.currentTime=Math.max(0,episode.start-0.35);loopEnd.current=Math.min(p.duration,episode.end+0.35);p.play().catch(()=>setError('Не удалось воспроизвести фрагмент'));}
 function download(){const blob=new Blob([JSON.stringify({schemaVersion:2,annotationFeaturesVersion:1,revision:revision.current,boundaryDefinition:'first airborne frame → first landing contact; source-file seconds; frame indices are zero-based',videos,episodes:current.current},null,2)],{type:'application/json'});const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='jump-annotations.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
 useEffect(()=>{const listener=(e:KeyboardEvent)=>{const el=e.target as HTMLElement;if(el.closest('input,textarea,button,[role="slider"],[role="combobox"],[role="listbox"]'))return;if(e.code==='Space'){e.preventDefault();toggle()}if(e.code==='ArrowLeft'){e.preventDefault();step(e.shiftKey?-10:-1)}if(e.code==='ArrowRight'){e.preventDefault();step(e.shiftKey?10:1)}if(e.code==='KeyI'){e.preventDefault();mark('start')}if(e.code==='KeyO'){e.preventDefault();mark('end')}};window.addEventListener('keydown',listener);return()=>window.removeEventListener('keydown',listener)});
 return <main>
  <header className="topbar"><div className="brand"><span className="brandmark">Л</span><strong>ЛЁД</strong><span className="divider"/><span>{axelOnly?'Аксели соревнований':'Разметка прыжков'}</span></div><div className="head-actions"><a className="mode-link" href={axelOnly?'/':'/axel-review'}>{axelOnly?'Все видео':'Аксели соревнований'}</a><span className={'save-status '+(dirty?'pending':'')} aria-live="polite">{!dirty&&loaded?<Check size={15}/>:null}{status}</span><Button variant="outline" onClick={download} disabled={!loaded}><Download/> Скачать разметку</Button></div></header>
  <div className="workspace">
   <VideoLibrary videos={shownVideos} episodes={episodes} vid={vid} axelOnly={axelOnly} onSelect={id=>{setVid(id);setActive(episodes.find(e=>e.videoId===id&&(!axelOnly||isAxelDraft(e)))?.id||'');setError('')}}/>
   <section className="editor"><div className="editor-heading"><div><span className="eyebrow">ВИДЕО {vid} / {shownVideos.length||15}</span><h1>{video?.title||'Загрузка видео…'}</h1></div><span className="meta">{video?`${video.width} × ${video.height}`:''}</span></div>
    {error?<div className="error" role="alert">{error}{failed?<Button variant="outline" onClick={retry}>Повторить сохранение</Button>:null}<button onClick={()=>setError('')} aria-label="Закрыть сообщение">×</button></div>:null}
    <div className="screen"><video key={vid} ref={player} src={'/media/'+vid} preload="auto" playsInline onClick={toggle} onLoadedMetadata={()=>setReady(true)} onSeeking={()=>setSeeking(true)} onSeeked={()=>{setSeeking(false);setT(player.current?.currentTime||0)}} onPlay={()=>setPlaying(true)} onPause={()=>setPlaying(false)} onEnded={()=>setPlaying(false)} onError={()=>{setReady(false);setError('Видео не загрузилось. Проверьте, что локальный сервер работает.')}} onTimeUpdate={()=>{const p=player.current!;setT(p.currentTime);if(loopEnd.current!==null&&p.currentTime>=loopEnd.current){p.pause();loopEnd.current=null}}}/><span className="screen-label">{playing?'ПРОСМОТР':'ПАУЗА'} · {rate}×</span></div>
    <div className="timeline"><div className="time-row"><strong>{time(t)}</strong><span>{frames.length?`Кадр ${frameIndex(t)+1} / ${frames.length}`:'Загрузка кадров…'}</span><span>{time(video?.duration||0)}</span></div><Slider aria-label="Позиция в видео" value={[t]} min={0} max={video?.duration||1} step={0.001} disabled={!ready} onValueChange={v=>seek(Array.isArray(v)?v[0]:v)}/><div className="interval-track">{list.filter(e=>e.start!==null&&e.end!==null).map(e=><button key={e.id} aria-label="Перейти к отмеченному эпизоду" onClick={()=>{setActive(e.id);seek(e.start!)}} style={{left:`${e.start!/(video?.duration||1)*100}%`,width:`${Math.max(.5,(e.end!-e.start!)/(video?.duration||1)*100)}%`}}/>)}</div></div>
    <div className="transport"><div className="transport-buttons"><Button aria-label="Предыдущий кадр" variant="outline" disabled={!ready||!frames.length||seeking} onClick={()=>step(-1)}><ChevronLeft/> Кадр</Button><Button className="play" disabled={!ready} onClick={toggle}>{playing?<Pause/>:<Play/>}{playing?'Пауза':'Смотреть'}</Button><Button aria-label="Следующий кадр" variant="outline" disabled={!ready||!frames.length||seeking} onClick={()=>step(1)}>Кадр <ChevronRight/></Button></div><Select value={rate} onValueChange={v=>v&&setRate(v)}><SelectTrigger aria-label="Скорость воспроизведения"><SelectValue/></SelectTrigger><SelectContent>{['0.1','0.25','0.5','1'].map(x=><SelectItem key={x} value={x}>{x}×</SelectItem>)}</SelectContent></Select></div>
    <div className="mark-grid"><button className="mark start" disabled={!loaded||!ready||seeking||!frames.length} onClick={()=>mark('start')}><span><Flag size={18}/> Начало прыжка <kbd>I</kbd></span><strong>{time(episode?.start??null)}</strong><small>Первый кадр без контакта со льдом</small></button><button className="mark end" disabled={!loaded||!ready||seeking||!frames.length} onClick={()=>mark('end')}><span><Flag size={18}/> Конец прыжка <kbd>O</kbd></span><strong>{time(episode?.end??null)}</strong><small>Первое касание льда при приземлении</small></button></div>
    <div className="episode-actions"><Button onClick={preview} disabled={episode?.start==null||episode?.end==null||!ready} variant="outline"><Play/> Проверить фрагмент</Button><span>{episode?.start!=null&&episode?.end!=null?`${(episode.end-episode.start).toFixed(3)} с в файле`:'Поставьте обе границы'}</span><Button variant="ghost" onClick={add} disabled={!loaded||axelOnly}><Plus/> Новый эпизод</Button></div>
    {episode?<EventEditor episode={episode} frames={frames} onMark={markPhase} disabled={!loaded||!ready||seeking||!frames.length} patch={patch} seek={seek}/>:null}
    <p className="help">← → по кадрам · Shift + ← → по 10 кадров · Пробел — пауза. Время относится к файлу: в замедленном повторе это не реальная длительность полёта.</p>
   </section>
   <EpisodePanel list={list} episode={episode} active={active} axelOnly={axelOnly} patch={patch} onSelect={e=>{setActive(e.id);const target=e.analysisProposal?.windowStart??e.start;if(target!==null&&target!==undefined)seek(target)}} onRemove={()=>{change(current.current.filter(e=>e.id!==active));setActive('')}} canUndo={!!undo} onUndo={undoChange}/>
  </div>
 </main>
}
