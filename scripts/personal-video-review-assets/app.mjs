import {AXELS,validate} from './core.mjs';
const $=id=>document.getElementById(id);
const data=await(await fetch('./data.json')).json(),key='personal-video-review:v1:'+data.datasetSha256;
const requested=Number(new URLSearchParams(location.search).get('video'));
let labels=[],index=Number.isInteger(requested)&&requested>=1&&requested<=data.items.length?requested-1:0,generation=0,video=null,ready=false;const drafts=new Map();
const payload=rows=>({schemaVersion:1,datasetSha256:data.datasetSha256,labels:rows});
try{const raw=localStorage.getItem(key);if(raw)labels=validate(JSON.parse(raw),data.items,data.datasetSha256);}catch(e){$('message').textContent='Сохранённые ответы не загружены: '+e.message;}
function status(){const item=data.items[index];$('position').textContent=`Видео ${index+1} / ${data.items.length} · сохранено ${labels.length}`;$('current').textContent=drafts.has(item.id)?'Изменения ещё не сохранены':labels.some(r=>r.id===item.id)?'Оценка сохранена':'Оценки пока нет';}
function controls(){const axel=AXELS.has($('element').value);$('element').disabled=!ready;$('rotation').disabled=!ready||!axel;$('group').disabled=!ready;$('save').disabled=!ready||!$('element').value||(axel&&!$('rotation').value);$('clear').disabled=!ready;}
function draft(){drafts.set(data.items[index].id,{element:$('element').value,rotation:$('rotation').value,athleteGroup:$('group').value});controls();status();}
$('element').onchange=()=>{if(!AXELS.has($('element').value))$('rotation').value='';draft();};$('rotation').onchange=draft;$('group').oninput=draft;
$('speed').onchange=()=>{if(video)video.playbackRate=Number($('speed').value);};
function show(){
 const token=++generation,item=data.items[index];ready=false;$('message').textContent='Загрузка видео…';if(video)video.pause();
 const saved=drafts.get(item.id)||labels.find(r=>r.id===item.id)||{};
 $('element').value=saved.element||'';$('rotation').value=saved.rotation||'';$('group').value=saved.athleteGroup||'';
 controls();status();$('previous').disabled=index===0;$('next').disabled=index===data.items.length-1;
 const next=document.createElement('video');next.controls=true;next.preload='auto';next.playsInline=true;next.setAttribute('aria-label',`Видео ${index+1}`);
 next.addEventListener('loadedmetadata',()=>{if(token===generation)next.playbackRate=Number($('speed').value);});
 next.addEventListener('loadeddata',()=>{if(token!==generation||next!==video||next.readyState<2)return;ready=true;$('message').textContent='';controls();});
 next.addEventListener('error',()=>{if(token!==generation||next!==video)return;ready=false;controls();$('message').textContent='Видео не загрузилось. Оценка отключена.';});
 video=next;$('player').replaceChildren(next);next.src=item.file;next.load();
}
function persist(){try{localStorage.setItem(key,JSON.stringify(payload(labels)));$('message').textContent='Сохранено в этом браузере.';}catch{$('message').textContent='Не удалось сохранить в браузере. Скачайте JSON перед закрытием.';}}
$('save').onclick=()=>{if(!ready)return;try{
 const item=data.items[index],record={id:item.id,sha256:item.sha256,element:$('element').value,rotation:AXELS.has($('element').value)?$('rotation').value:null,athleteGroup:$('group').value.trim()||null};
 const [clean]=validate(payload([record]),data.items,data.datasetSha256);labels=labels.filter(r=>r.id!==item.id);labels.push(clean);drafts.delete(item.id);persist();status();
 }catch(e){$('message').textContent=e.message;}};
$('clear').onclick=()=>{const id=data.items[index].id;labels=labels.filter(r=>r.id!==id);drafts.delete(id);$('element').value='';$('rotation').value='';$('group').value='';persist();controls();status();};
$('previous').onclick=()=>{if(index>0){index--;show();}};$('next').onclick=()=>{if(index<data.items.length-1){index++;show();}};
$('unanswered').onclick=()=>{const found=Array.from({length:data.items.length},(_,n)=>(index+n+1)%data.items.length).find(i=>!labels.some(r=>r.id===data.items[i].id));if(found!==undefined){index=found;show();}else $('message').textContent='Все видео оценены.';};
$('export').onclick=()=>{const clean=validate(payload(labels),data.items,data.datasetSha256);const url=URL.createObjectURL(new Blob([JSON.stringify(payload(clean),null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='personal-video-expert-review.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);$('message').textContent=`Скачаны сохранённые оценки: ${clean.length}. Несохранённые изменения не включены.`;};
show();
