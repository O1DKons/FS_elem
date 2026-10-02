import {useState} from 'react';
import {Check} from 'lucide-react';
import type {Episode,Video} from '@/lib/annotation-types';
export function VideoLibrary({videos,episodes,vid,onSelect,axelOnly=false}:{videos:Video[];episodes:Episode[];vid:string;onSelect:(id:string)=>void;axelOnly?:boolean}){
    const [collection,setCollection]=useState<'all'|'competition'|'earlier'>('all');
    const shown=videos.filter(v=>collection==='all'||(collection==='competition')===(v.collection==='competition'));
    return <section className="library" aria-label="Библиотека видео">
    <div className="library-head"><span className="eyebrow">БИБЛИОТЕКА</span><span>{videos.length} видео</span></div>
    <h2>{axelOnly?'Аксели':'Прыжки'}</h2><p className="muted">{axelOnly?'Прокаты с детализацией':'Тренировки и соревнования'}</p>
    {!axelOnly?<div className="library-filters" aria-label="Фильтр видео">{([['all','Все'],['competition','Соревнования'],['earlier','Ранее']] as const).map(([key,label])=><button key={key} type="button" aria-pressed={collection===key} onClick={()=>setCollection(key)}>{label}</button>)}</div>:null}
    <div className="video-list">{shown.map(v=>{
     const count=episodes.filter(e=>e.videoId===v.id&&e.start!==null&&e.end!==null).length;
     const sourceLabel=v.collection==='competition'?'Соревнования · протокол':v.collection==='personal'?'Личное · оценка не подтверждена':v.collection==='ssd-personal'?(v.labelStatus==='expert_confirmed_type_and_grade'?'SSD · подтверждено тренером':'SSD · тип не подтверждён'):v.title.startsWith('Двойной')?'2A':v.title.startsWith('Четверной')?'4A':'3A';
     return <button className={'video-item '+(vid===v.id?'selected':'')} key={v.id} onClick={()=>onSelect(v.id)}>
      <span className="video-number">{v.id}</span><span><strong>{v.title.replace(/^(Тройной|Двойной|Четверной) Аксель /,'')}</strong><small>{sourceLabel} · {Math.round(v.duration)} сек.{count>0?` · отмечено ${count}`:''}</small></span>{count>0?<Check className="done" size={15}/>:null}
     </button>
    })}</div>
    <div className="library-footer">{axelOnly?'Отметки протокола показаны отдельно от визуальных предложений. Проверяйте первый контакт приземления.':'Для соревнований названия прыжков взяты из протокола. Границы в видео ещё не размечены.'}</div>
   </section>;}
