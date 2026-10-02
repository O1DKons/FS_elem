import {key,validateLabels,initialLabels} from './facing-core.mjs';
const $=id=>document.getElementById(id);
let frames=[],labels=new Map(),index=0,token=0,loading=true,storage,hasImage=false;
const status=text=>$('status').textContent=text;
const pendingButton=document.createElement('button');pendingButton.textContent='Следующий без оценки';$('next').after(pendingButton);
pendingButton.onclick=()=>{if(loading)return;const n=frames.findIndex((r,i)=>i>index&&!labels.has(key(r)));const first=frames.findIndex(r=>!labels.has(key(r)));if(first<0){status('Все кадры отмечены. Экспортируйте JSON.');return;}show(n<0?first:n);};
function render(){
 $('frame').value=index;
 $('progress').textContent=`Кадр ${index+1} / ${frames.length} · отмечено ${labels.size} / ${frames.length}`;
 for(const b of document.querySelectorAll('[data-facing]')){b.disabled=loading;b.setAttribute('aria-pressed',String(labels.get(key(frames[index]))?.facing===b.dataset.facing));}
 $('clear').disabled=loading||!labels.has(key(frames[index]));
 $('prev').disabled=index===0;$('next').disabled=index===frames.length-1;
 $('source').href=`boot-workbench.html?attempt=${frames[index].attemptId}&frame=${frames[index].frameIndex}&side=landing`;
}
async function show(n){
 const current=++token;loading=true;render();
 try{const img=new Image();img.src=frames[n].image;await img.decode();if(current!==token)return;
  index=n;$('image').src=img.src;hasImage=true;loading=false;render();
 }catch(e){if(current===token){loading=!hasImage;render();status('Не удалось загрузить кадр. Попробуйте ещё раз.');}}
}
function save(facing){
 if(loading)return;
 const next=new Map(labels),r=frames[index];
 if(facing)next.set(key(r),{attemptId:r.attemptId,frameIndex:r.frameIndex,sourceSha256:r.sourceSha256,sourceFrameSha256:r.sourceFrameSha256,facing});else next.delete(key(r));
 try{const payload={schemaVersion:1,labels:[...next.values()]};validateLabels(payload,frames);localStorage.setItem(storage,JSON.stringify(payload));labels=next;render();status('Оценка сохранена. Нажмите «Далее», чтобы продолжить.');}
 catch(e){status('Не удалось сохранить. Экспортируйте уже сохранённые оценки.');}
}
for(const b of document.querySelectorAll('[data-facing]'))b.onclick=()=>save(b.dataset.facing);
$('clear').onclick=()=>save(null);
$('prev').onclick=()=>show(Math.max(0,index-1));$('next').onclick=()=>show(Math.min(frames.length-1,index+1));
$('frame').onchange=()=>show(Number($('frame').value));
$('export').onclick=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify({schemaVersion:1,scope:'diagnostic-facing-review',labels:[...labels.values()]},null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='facing-expert-review.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
try{const response=await fetch(location.pathname.endsWith('facing-review-expanded.html')?'facing-review-expanded-data.json':'facing-review-data.json');if(!response.ok)throw Error('HTTP');const data=await response.json();frames=data.frames;if(data.schemaVersion!==1||!frames?.length)throw Error('Manifest');
 storage='facing-review:v1:'+JSON.stringify(frames.map(key));
 const raw=localStorage.getItem(storage);labels=initialLabels(raw,data.seedLabels||[],frames);
 frames.forEach((r,i)=>{const o=document.createElement('option');o.value=i;o.textContent=`${r.athlete} · ${r.frameIndex} (${r.offset>=0?'+':''}${r.offset})`;$('frame').append(o);});
 await show(Math.max(0,frames.findIndex(r=>!labels.has(key(r)))));
}catch(e){status('Не удалось открыть разметку. Сохранённые данные не перезаписаны.');document.querySelectorAll('button,select').forEach(b=>b.disabled=true);}
