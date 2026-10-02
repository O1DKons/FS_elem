'use strict';
const $ = id => document.getElementById(id);
const format = value => value.toFixed(3).replace('.', ',');
let selected, local = false, objectUrl, playing = false, animation, lastTick;
const seek = $('seek');
function stop() { playing = false; cancelAnimationFrame(animation); $('play').innerHTML = '▶ <span>Воспроизвести</span>'; $('play').setAttribute('aria-label', 'Воспроизвести иллюстрацию'); }
function renderTime() {
 const time = Number(seek.value); $('scene-time').textContent = format(time) + ' с';
 if (local) return;
 const inFlight = time >= selected.start && time <= selected.end;
 $('phase').textContent = inFlight ? 'Полёт' : time < selected.start ? 'Подход' : 'Выезд';
 const progress = Math.min(1,Math.max(0,(time-selected.start)/(selected.end-selected.start)));
 const lift = inFlight ? Math.sin(progress*Math.PI)*45 : -35;
 $('athlete').setAttribute('transform', `translate(${(time/selected.duration-.5)*110},${-lift})`);
 $('shadow').setAttribute('rx', String(inFlight ? 38 : 64));
}
function setTime(value) { seek.value = Math.min(Number(seek.max),Math.max(0,value)); if(local) $('local-video').currentTime=Number(seek.value); renderTime(); }
function selectExample() {
 stop(); local=false; document.body.classList.remove('local-mode'); $('local-video').pause(); $('local-video').removeAttribute('src'); $('local-video').hidden=true; $('illustration').hidden=false;
 if(objectUrl) { URL.revokeObjectURL(objectUrl); objectUrl=undefined; }
 $('local-notice').hidden=true; selected=window.FS_EXAMPLES.find(e=>e.id===$('example').value);
 $('nominal').textContent=selected.nominal; $('nominal-description').textContent=selected.nominal==='1A'?'Одинарный аксель':'Двойной аксель';
 $('result-title').textContent='Номинал прыжка';$('family').textContent='Аксель';$('search').textContent='Автоматический';$('result-origin').textContent='Проверенный запуск v4 от 1 октября 2026. Ответ загружен из сохранённого результата, новый анализ не выполняется.';$('result-overlap').textContent='Исходник участвовал в обучении поиска и семейства.'; $('interval').textContent=`${format(selected.start)}–${format(selected.end)} с`;
 $('start-value').textContent=format(selected.start)+' с'; $('end-value').textContent=format(selected.end)+' с';
 $('duration').textContent=format(selected.duration)+' с'; $('tick-middle').textContent=format(selected.duration/2)+' с'; $('tick-end').textContent=format(selected.duration)+' с';
 $('approach').style.width=(selected.start/selected.duration*100)+'%'; $('flight').style.width=((selected.end-selected.start)/selected.duration*100)+'%'; $('exit').style.width=((selected.duration-selected.end)/selected.duration*100)+'%';
 $('cold').textContent=format(selected.coldSeconds)+' с'; $('warm').textContent=format(selected.warmSeconds)+' с';
 $('source-hash').textContent=selected.sourceSha256; $('receipt-hash').textContent=selected.receiptSha256; $('recipe-hash').textContent=selected.recipeSha256;
 seek.max=selected.duration;seek.disabled=false;seek.setAttribute('aria-label','Время на шкале сохранённого примера');$('playback-note').textContent='Схематический просмотр';$('play').disabled=false;$('takeoff').disabled=false;$('landing').disabled=false;
 document.querySelector('.result .saved').textContent='Сохранённый пример';setTime((selected.start+selected.end)/2);
}
$('example').addEventListener('change',selectExample);
seek.addEventListener('input',()=>{stop();setTime(Number(seek.value));});
$('previous').addEventListener('click',()=>{stop();setTime(Number(seek.value)-.01);});
$('next').addEventListener('click',()=>{stop();setTime(Number(seek.value)+.01);});
$('takeoff').addEventListener('click',()=>{stop();setTime(selected.start);});
$('landing').addEventListener('click',()=>{stop();setTime(selected.end);});
$('play').addEventListener('click',()=>{
 if(local){ const video=$('local-video');if(video.paused) video.play().catch(()=>{$('local-notice').textContent='Браузер не смог воспроизвести файл. Попробуйте MP4/H.264.';});else video.pause();return; }
 if(playing){stop();return;} if(Number(seek.value)>=selected.duration) setTime(0);
 playing=true;lastTick=performance.now();$('play').innerHTML='Ⅱ <span>Пауза</span>';$('play').setAttribute('aria-label','Пауза иллюстрации');
 const tick=now=>{if(!playing)return;setTime(Number(seek.value)+(now-lastTick)/1000);lastTick=now;if(Number(seek.value)>=selected.duration)stop();else animation=requestAnimationFrame(tick);};animation=requestAnimationFrame(tick);
});
$('open-video').addEventListener('click',()=>{$('file').value='';$('file').click();});
$('file').addEventListener('change',()=>{
 const file=$('file').files[0];if(!file)return;stop();local=true;document.body.classList.add('local-mode');
 if(objectUrl)URL.revokeObjectURL(objectUrl);objectUrl=URL.createObjectURL(file);$('local-video').src=objectUrl;$('local-video').hidden=false;$('illustration').hidden=true;
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
