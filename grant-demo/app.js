'use strict';
const $ = id => document.getElementById(id);
const format = value => value.toFixed(3).replace('.', ',');
let selected, local = false, objectUrl, jumpEnd;
const exampleVideo = $('example-video');
const activeVideo = () => local ? $('local-video') : exampleVideo;
const seek = $('seek');
function stop() { activeVideo().pause(); jumpEnd = undefined; }
function renderTime() {
 const time = Number(seek.value); $('scene-time').textContent = format(time) + ' с';
 if (local) return;
 $('phase').textContent = time >= selected.start - .0005 && time <= selected.end + .0005 ? 'Прыжок' : time < selected.start ? 'Подход' : 'Выезд';
}
function setTime(value) {
 seek.value = Math.min(Number(seek.max),Math.max(0,value));
 const video = activeVideo();
 if (video.readyState >= 1) video.currentTime = Number(seek.value);
 renderTime();
}
function selectExample() {
 stop(); local=false; document.body.classList.remove('local-mode'); $('local-video').pause(); $('local-video').removeAttribute('src'); $('local-video').hidden=true; exampleVideo.hidden=false;document.querySelector('.video-label').hidden=false;
 if(objectUrl) { URL.revokeObjectURL(objectUrl); objectUrl=undefined; }
 $('local-notice').hidden=true; selected=window.FS_EXAMPLES.find(e=>e.id===$('example').value);exampleVideo.src=selected.media;
 $('nominal').textContent=selected.nominal; $('nominal-description').textContent=selected.nominal==='1A'?'Одинарный аксель':'Двойной аксель';
 $('result-title').textContent='Номинал прыжка';$('family').textContent='Аксель';$('search').textContent='Автоматический';$('result-origin').textContent='Проверенный запуск v4 от 1 октября 2026. Ответ загружен из сохранённого результата, новый анализ не выполняется.';$('result-overlap').textContent='Исходник участвовал в обучении поиска и семейства.'; $('interval').textContent=`${format(selected.start)}–${format(selected.end)} с`;
 $('start-value').textContent=format(selected.start)+' с'; $('end-value').textContent=format(selected.end)+' с';
 $('duration').textContent=format(selected.duration)+' с'; $('tick-middle').textContent=format(selected.duration/2)+' с'; $('tick-end').textContent=format(selected.duration)+' с';
 $('approach').style.width=(selected.start/selected.duration*100)+'%'; $('flight').style.width=((selected.end-selected.start)/selected.duration*100)+'%'; $('exit').style.width=((selected.duration-selected.end)/selected.duration*100)+'%';
 $('cold').textContent=format(selected.coldSeconds)+' с'; $('warm').textContent=format(selected.warmSeconds)+' с';
 $('source-hash').textContent=selected.sourceSha256; $('receipt-hash').textContent=selected.receiptSha256; $('recipe-hash').textContent=selected.recipeSha256;
 seek.max=selected.duration;seek.disabled=false;seek.setAttribute('aria-label','Время на шкале сохранённого примера');$('playback-note').textContent='Сохранённый видеофрагмент';$('jump').hidden=false;$('play').disabled=false;$('takeoff').disabled=false;$('landing').disabled=false;
 document.querySelector('.result .saved').textContent='Сохранённый пример';setTime((selected.start+selected.end)/2);
}
$('example').addEventListener('change',selectExample);
seek.addEventListener('input',()=>{stop();setTime(Number(seek.value));});
$('previous').addEventListener('click',()=>{stop();setTime(Number(seek.value)-.01);});
$('next').addEventListener('click',()=>{stop();setTime(Number(seek.value)+.01);});
$('takeoff').addEventListener('click',()=>{stop();setTime(selected.start);});
$('landing').addEventListener('click',()=>{stop();setTime(selected.end);});
$('play').addEventListener('click',()=>{
 const video=activeVideo();jumpEnd=undefined;
 if(video.paused) video.play().catch(()=>{});else stop();
});
$('jump').addEventListener('click',()=>{
 stop();setTime(Math.max(0,selected.start-.45));jumpEnd=Math.min(selected.duration,selected.end+.4);
 exampleVideo.play().catch(()=>{});
});
for(const video of [exampleVideo,$('local-video')]) {
 video.addEventListener('play',()=>{$('play').innerHTML='Ⅱ <span>Пауза</span>';$('play').setAttribute('aria-label','Пауза видео');});
 video.addEventListener('pause',()=>{$('play').innerHTML='▶ <span>Воспроизвести</span>';$('play').setAttribute('aria-label','Воспроизвести видео');});
 video.addEventListener('timeupdate',()=>{
  if(video!==activeVideo())return;seek.value=video.currentTime;renderTime();
  if(jumpEnd!==undefined && video.currentTime>=jumpEnd){const end=jumpEnd;stop();setTime(end);}
 });
}
exampleVideo.addEventListener('loadedmetadata',()=>{if(!local)setTime((selected.start+selected.end)/2);});
exampleVideo.addEventListener('error',()=>{if(!local){$('phase').textContent='Видео не загрузилось';$('playback-note').textContent='Обновите страницу или выберите своё видео';}});
$('open-video').addEventListener('click',()=>{$('file').value='';$('file').click();});
$('file').addEventListener('change',()=>{
 const file=$('file').files[0];if(!file)return;stop();local=true;document.body.classList.add('local-mode');
 if(objectUrl)URL.revokeObjectURL(objectUrl);objectUrl=URL.createObjectURL(file);$('local-video').src=objectUrl;$('local-video').hidden=false;exampleVideo.pause();exampleVideo.hidden=true;document.querySelector('.video-label').hidden=true;$('jump').hidden=true;
 $('local-notice').hidden=false;$('local-notice').textContent='Локальное видео: '+file.name+'. Доступен только просмотр. Анализ и распознавание не выполняются; сохранённый ответ относится к другому источнику.';
 $('nominal').textContent='Нет результата';$('nominal-description').textContent='Видео открыто для просмотра';$('result-title').textContent='Новое локальное видео';$('interval').textContent='Не определён';document.querySelector('.result .saved').textContent='Режим просмотра';
 $('family').textContent='Не определено';$('search').textContent='Не выполнялся';$('result-origin').textContent='Выбранный файл открыт только в браузере и не отправляется на сервер. Сохранённые примеры доступны в списке сверху.';$('result-overlap').textContent='Результат распознавания для этого файла отсутствует.';$('phase').textContent='Локальное видео';$('playback-note').textContent='Без анализа';seek.disabled=true;seek.setAttribute('aria-label','Время локального видео');$('duration').textContent='Загрузка видео';$('scene-time').textContent='0,000 с';$('takeoff').disabled=true;$('landing').disabled=true;
 $('approach').style.width='100%';$('flight').style.width='0%';$('exit').style.width='0%';$('tick-middle').textContent='';$('tick-end').textContent='';
});
$('local-video').addEventListener('loadedmetadata',()=>{const duration=$('local-video').duration;if(Number.isFinite(duration)){seek.max=duration;seek.value=0;seek.disabled=false;$('duration').textContent=format(duration)+' с';$('tick-end').textContent=format(duration)+' с';$('tick-middle').textContent=format(duration/2)+' с';}});
$('local-video').addEventListener('timeupdate',()=>{if(local){seek.value=$('local-video').currentTime;renderTime();}});
$('local-video').addEventListener('error',()=>{if(local){seek.disabled=true;$('duration').textContent='Файл не воспроизводится';$('local-notice').textContent='Браузер не смог открыть этот файл. Выберите совместимое видео MP4/H.264. Анализ не выполнялся.';}});
document.addEventListener('visibilitychange',()=>{if(document.hidden)stop();});
selectExample();
