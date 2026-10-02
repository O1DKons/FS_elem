import {validate, validateAthleteGroups} from './core.mjs';
const data=await (await fetch('./data.json')).json();
const key='rotation-video-review:'+data.datasetSha256;
const groupKey='rotation-video-athlete-groups:'+data.datasetSha256;
let labels=[];
try { const raw=localStorage.getItem(key); if(raw) labels=validate(JSON.parse(raw),data.items); } catch(e) { document.querySelector('#message').textContent='Не удалось прочитать сохранённые оценки: '+e.message; }
let athleteGroups=[];
try { const raw=localStorage.getItem(groupKey); if(raw) athleteGroups=validateAthleteGroups(JSON.parse(raw),data.items,data.datasetSha256); } catch(e) { document.querySelector('#groupProgress').textContent='Не удалось прочитать сохранённые группы: '+e.message; }
let index=0;
const video=document.querySelector('video');
const buttons=[...document.querySelectorAll('[data-assessment]')];
const speed=document.querySelector('#speed');
const groupInput=document.querySelector('#athleteGroup');
speed.onchange=()=>{video.playbackRate=Number(speed.value)};
video.addEventListener('loadedmetadata',()=>{video.playbackRate=Number(speed.value)});
function updateProgress() {
 const groupCount=new Set(athleteGroups.map(r=>r.athleteGroup)).size;
 document.querySelector('#groupProgress').textContent=`Назначено ${athleteGroups.length} / ${data.items.length} видео · ${groupCount} групп спортсменов`;
}
function show() {
 const item=data.items[index];
 document.querySelector('#position').textContent=`Видео ${index+1} / ${data.items.length} · оценено ${labels.length}`;
 document.querySelector('#current').textContent=labels.find(r=>r.id===item.id)?.assessment ?? 'Оценки пока нет';
 groupInput.value=athleteGroups.find(r=>r.id===item.id)?.athleteGroup ?? '';
 groupInput.disabled=true;buttons.forEach(b=>b.disabled=true);video.src=item.file;video.load();
 document.querySelector('#previous').disabled=index===0;document.querySelector('#next').disabled=index===data.items.length-1;
}
video.addEventListener('loadeddata',()=>{if(video.readyState>=2){buttons.forEach(b=>b.disabled=false);groupInput.disabled=false}});
video.addEventListener('error',()=>{buttons.forEach(b=>b.disabled=true);document.querySelector('#message').textContent='Видео не загрузилось. Не ставьте оценку вслепую.'});
buttons.forEach(b=>b.addEventListener('click',()=>{
 const item=data.items[index];labels=labels.filter(r=>r.id!==item.id);labels.push({id:item.id,sha256:item.sha256,assessment:b.dataset.assessment});
 try {localStorage.setItem(key,JSON.stringify({schemaVersion:1,labels}));document.querySelector('#current').textContent=b.textContent;document.querySelector('#message').textContent='Оценка сохранена в этом браузере.';} catch(e){document.querySelector('#message').textContent='Не удалось сохранить в браузере. Скачайте JSON перед закрытием страницы.';}
 document.querySelector('#position').textContent=`Видео ${index+1} / ${data.items.length} · оценено ${labels.length}`;
}));
document.querySelector('#previous').onclick=()=>{if(index>0){index--;show()}};
document.querySelector('#next').onclick=()=>{if(index<data.items.length-1){index++;show()}};
groupInput.addEventListener('change',()=>{
 const item=data.items[index],group=groupInput.value.trim();
 athleteGroups=athleteGroups.filter(r=>r.id!==item.id);
 if(group)athleteGroups.push({id:item.id,sha256:item.sha256,athleteGroup:group});
 try {
  athleteGroups=validateAthleteGroups({schemaVersion:1,datasetSha256:data.datasetSha256,assignments:athleteGroups},data.items,data.datasetSha256);
  localStorage.setItem(groupKey,JSON.stringify({schemaVersion:1,datasetSha256:data.datasetSha256,assignments:athleteGroups}));
  document.querySelector('#message').textContent='Группа спортсмена сохранена отдельно от оценки докрута.';
 } catch(e) {document.querySelector('#message').textContent='Не удалось сохранить группу: '+e.message;}
 updateProgress();
});
document.querySelector('#export').onclick=()=>{
 const blob=new Blob([JSON.stringify({schemaVersion:1,datasetSha256:data.datasetSha256,labels},null,2)],{type:'application/json'});
 const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='rotation-video-expert-review.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};
document.querySelector('#exportGroups').onclick=()=>{
 const assignments=data.items.flatMap(item=>{
  const row=athleteGroups.find(r=>r.id===item.id);
  return row?[row]:[];
 });
 const payload={schemaVersion:1,datasetSha256:data.datasetSha256,assignments};
 try {
  validateAthleteGroups(payload,data.items,data.datasetSha256);
  const blob=new Blob([JSON.stringify(payload,null,2)],{type:'application/json'});
  const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='rotation-video-athlete-groups.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  document.querySelector('#message').textContent=`Скачан экспорт: ${assignments.length} из ${data.items.length} видео сгруппировано.`;
 } catch(e) {document.querySelector('#message').textContent='Не удалось подготовить экспорт: '+e.message;}
};
updateProgress();
show();
