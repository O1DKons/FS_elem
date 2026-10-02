'use client';
import {useEffect,useRef,useState} from 'react';
import {createAnnotationClient} from '@/lib/annotation-client.mjs';
import {createAnnotationPersistence} from '@/lib/annotation-persistence.mjs';
import type {Episode,Video} from '@/lib/annotation-types';
export const annotationClient=createAnnotationClient();
export function useAnnotations(){
 const [videos,setVideos]=useState<Video[]>([]),[episodes,setEpisodes]=useState<Episode[]>([]);
 const [loaded,setLoaded]=useState(false),[dirty,setDirty]=useState(false),[saving,setSaving]=useState(false),[failed,setFailed]=useState(false),[error,setError]=useState(''),[undo,setUndo]=useState<Episode[]|null>(null);
 const current=useRef<Episode[]>([]),revision=useRef(0),writer=useRef<ReturnType<typeof createAnnotationPersistence>|null>(null);
 useEffect(()=>{
  let cancelled=false;
  Promise.all([annotationClient.catalog(),annotationClient.annotations()]).then(([catalog,saved])=>{
   if(cancelled)return;
   setVideos(catalog);setEpisodes(saved.episodes);current.current=saved.episodes;revision.current=saved.revision;
   writer.current=createAnnotationPersistence({revision:saved.revision,save:annotationClient.save,onSaved:(snapshot,nextRevision)=>{revision.current=nextRevision;if(!cancelled&&current.current===snapshot)setDirty(false);},onState:state=>{if(cancelled)return;setSaving(state.saving);setFailed(state.failed);if(state.error)setError((state.error instanceof Error?state.error.message:'Не удалось сохранить разметку')+' Разметка остаётся на экране: скачайте копию.');}});
   setLoaded(true);
  }).catch(cause=>{if(!cancelled)setError(cause.message);});
  return()=>{cancelled=true;};
 },[]);
 useEffect(()=>{if(!loaded||!dirty||failed)return;const timer=setTimeout(()=>writer.current?.enqueue(episodes),400);return()=>clearTimeout(timer);},[episodes,dirty,loaded,failed]);
 useEffect(()=>{const listener=(event:BeforeUnloadEvent)=>{if(dirty||saving){event.preventDefault();event.returnValue='';}};window.addEventListener('beforeunload',listener);return()=>window.removeEventListener('beforeunload',listener);},[dirty,saving]);
 function change(next:Episode[]){if(!loaded)return;setUndo(current.current);current.current=next;setEpisodes(next);setDirty(true);}
 function undoChange(){if(!undo)return;current.current=undo;setEpisodes(undo);setUndo(null);setDirty(true);}
 function retry(){if(!loaded)return;setError('');writer.current?.retry(current.current);}
 const status=failed?'Не сохранено':saving?'Сохраняю…':dirty?'Есть изменения…':loaded?'Сохранено на компьютере':'Загрузка…';
 return {videos,episodes,loaded,dirty,saving,failed,error,setError,undo,undoChange,current,revision,change,retry,status};
}
