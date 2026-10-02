import {angle,keyFor,validateImport,exportLabels,Drafts,viewTransform,canvasToSource,sourceToCanvas,mergeLabels,selectionFromQuery,focusCrop,FrameLoader,landingTrace} from './boot-workbench-core.mjs';
const $=id=>document.getElementById(id), canvas=$('canvas'),ctx=canvas.getContext('2d');
let data,item,index=0,labels=new Map(),draft=null,active='heel',image=null,timer=null,requestedItem=null,requestedIndex=0,loading=false;
let storage;
const drafts=new Drafts();
const tracePanel=document.createElement('section');
tracePanel.innerHTML='<h2>Направление конька по кадрам</h2><p>Автоматические точки · угол на изображении. Нажмите на график для перехода к кадру.</p><canvas id="trace" width="1000" height="180" style="width:100%;height:180px" aria-label="График направления конька"></canvas><p id="trace-summary"></p><p class="muted">Жёлтая линия — первое касание, голубая — текущий кадр. Разрывы — недостаточно данных или переход через ±180°. Разница направлений на изображении не является недокрутом или числом оборотов. Ручные поправки не заменяют автоматический график.</p>';
document.querySelector('footer').before(tracePanel);
function drawTrace(){
 const rows=landingTrace(item,$('side').value,data.fps);
 const chart=$('trace'),g=chart.getContext('2d'),w=chart.width,h=chart.height;
 const first=rows[0].frameIndex,last=rows.at(-1).frameIndex;
 const x=n=>45+(n-first)/Math.max(1,last-first)*(w-60),y=a=>15+(180-a)/360*(h-40);
 g.clearRect(0,0,w,h);g.font='12px Arial';
 for(const a of [-180,0,180]){g.strokeStyle='#344353';g.beginPath();g.moveTo(45,y(a));g.lineTo(w-15,y(a));g.stroke();g.fillStyle='#b8c8d8';g.fillText(a+'°',0,y(a)+4);}
 g.strokeStyle='#ffd083';g.beginPath();g.moveTo(x(item.firstContact),10);g.lineTo(x(item.firstContact),h-20);g.stroke();
 let previous=null;
 for(const r of rows){
  if(r.heading===null){previous=null;continue;}
  g.strokeStyle='#8bebaa';g.fillStyle='#8bebaa';
  if(previous&&r.frameIndex===previous.frameIndex+1&&Math.abs(r.heading-previous.heading)<=180){g.beginPath();g.moveTo(x(previous.frameIndex),y(previous.heading));g.lineTo(x(r.frameIndex),y(r.heading));g.stroke();}
  g.beginPath();g.arc(x(r.frameIndex),y(r.heading),2,0,Math.PI*2);g.fill();previous=r;
 }
 g.strokeStyle='#7ed9ff';g.beginPath();g.moveTo(x(frame().frameIndex),10);g.lineTo(x(frame().frameIndex),h-20);g.stroke();
 g.fillStyle='#b8c8d8';g.fillText(String(first),45,h-3);g.fillText(String(last),w-50,h-3);
 const current=rows[index],reference=rows.find(r=>r.frameIndex===item.firstContact);
 $('trace-summary').textContent=reference?.heading==null?'В первом касании нет надёжных ориентиров: разница недоступна.':current.delta===null?'Текущий кадр: направление недоступно.':'От первого касания: '+current.delta.toFixed(1)+'° · время '+current.seconds.toFixed(3)+' с.';
}
$('trace').onclick=e=>{
 if(!item||loading)return;stop();const r=$('trace').getBoundingClientRect();
 const fraction=Math.max(0,Math.min(1,((e.clientX-r.left)/r.width*1000-45)/940));
 const target=item.frames[0].frameIndex+fraction*(item.frames.at(-1).frameIndex-item.frames[0].frameIndex);
 const nearest=item.frames.reduce((best,f,i)=>Math.abs(f.frameIndex-target)<Math.abs(item.frames[best].frameIndex-target)?i:best,0);
 move(nearest);
};
const loader=new FrameLoader(src=>new Promise((resolve,reject)=>{
 const next=new Image();
 next.onload=async()=>{try{await next.decode();resolve(next);}catch(error){reject(error);}};
 next.onerror=()=>reject(Error('Не удалось загрузить кадр.'));
 next.src=src;
}));
const reasons={outside_landing_window:'вне окна приземления',landing_choice_ambiguous:'неоднозначный выбор конька у льда',landing_motion_jump:'резкое смещение выбранного конька',landing_candidates_missing:'нет доступных кандидатов конька у льда',orientation_jump:'резкое изменение направления между кадрами',side_identity_change:'неоднозначность левой и правой стопы между кадрами',low_model_response:'слабый отклик модели',foreshortened:'сильное перспективное сокращение',mirror_disagreement:'несогласованность при зеркальной проверке',feet_overlap:'ботинки перекрываются',implausible_span:'неправдоподобная длина ботинка',invalid_or_outside:'некорректные точки или точки вне кадра'};
const view=()=>{const fallback=Array.isArray(item.crop)?item.crop:[0,0,data.width,data.height];const crop=$('zoom').value==='focus'?(focusCrop(frame().candidates?.find(c=>c.side===$('side').value),data.width,data.height)||fallback):$('zoom').value==='feet'?fallback:[0,0,data.width,data.height];return viewTransform(crop,data.width,data.height);};
const status=text=>$('status').textContent=text;
const frame=()=>item.frames[index];
const identity=()=>({attemptId:item.attemptId,sourceSha256:item.sourceSha256,frameIndex:frame().frameIndex,sourceFrameSha256:frame().sourceFrameSha256,side:$('side').value});
function stop(){clearInterval(timer);timer=null;$('play').textContent='▶ 0,1×';}
function persist(next){localStorage.setItem(storage,exportLabels([...next.values()]));labels=next;}
function resetDraft(){if(!item)return;const saved=labels.get(keyFor(identity()));draft=drafts.get(keyFor(identity())) || (saved?.status==='manual'?{heel:[...saved.heel],toe:[...saved.toe]}:{heel:null,toe:null});active='heel';}
function draw(){
 if(!item||!image)return;
 drawTrace();
 $('side-explanation').textContent=$('side').value==='landing'?'Кандидат по положению у льда. При падении или перекрытии проверьте выбор.':'Левая/правая — предположение модели об анатомической стороне; проверяйте при перекрытии.';
 const url=new URL(location.href);url.searchParams.set('attempt',item.attemptId);url.searchParams.set('frame',String(frame().frameIndex));url.searchParams.set('side',$('side').value);history.replaceState(null,'',url);
 const eligible=$('side').value==='landing'?item.frames.filter(f=>f.frameIndex>=item.firstContact-2):item.frames;const available=eligible.filter(f=>f.candidates?.some(c=>c.side===$('side').value&&c.status==='visible')).length;$('availability').textContent=`Автоориентиры: ${available} / ${eligible.length} кадров ${$('side').value==='landing'?'окна приземления':'для выбранной стороны'}; это доступность, не точность.`;
 ctx.clearRect(0,0,data.width,data.height);const v=view();if(image)ctx.drawImage(image,v.x0,v.y0,v.x1-v.x0,v.y1-v.y0,v.dx,v.dy,(v.x1-v.x0)*v.scale,(v.y1-v.y0)*v.scale);
 const saved=labels.get(keyFor(identity())),manual=$('mode').value==='manual';
 const candidate=frame().candidates?.find(c=>c.side===$('side').value);
 let points=manual?(saved?.status==='unobservable'&&!draft?.heel&&!draft?.toe?null:draft):candidate;
 const uncertain=!manual&&candidate?.status!=='visible';
 const visible=points&&(!uncertain||$('diagnostic').checked);
 if(visible){ctx.save();ctx.beginPath();ctx.rect(v.dx,v.dy,(v.x1-v.x0)*v.scale,(v.y1-v.y0)*v.scale);ctx.clip();ctx.lineWidth=3;ctx.strokeStyle=manual?'#7ed9ff':uncertain?'#ffd083':'#8bebaa';ctx.fillStyle=ctx.strokeStyle;ctx.setLineDash(uncertain?[10,8]:[]);if(points.heel&&points.toe){ctx.beginPath();ctx.moveTo(...sourceToCanvas(points.heel,v));ctx.lineTo(...sourceToCanvas(points.toe,v));ctx.stroke();}for(const [name,label] of [['heel','П'],['toe','Н']]){const source=points[name];if(!source)continue;const p=sourceToCanvas(source,v);ctx.beginPath();ctx.arc(...p,7,0,Math.PI*2);ctx.stroke();ctx.font='bold 20px Arial';ctx.strokeStyle='#000';ctx.lineWidth=4;ctx.strokeText(label,p[0]+12,p[1]-10);ctx.fillText(label,p[0]+12,p[1]-10);}ctx.restore();}
 const degrees=uncertain?null:angle(points?.heel,points?.toe);
 $('angle').textContent=degrees===null?'Угол недоступен':`${degrees.toFixed(1)}°`;
 $('origin').textContent=manual?(saved?.status==='unobservable'&&!draft?.heel&&!draft?.toe?'Ручная: неразличим':saved?.status==='manual'&&JSON.stringify(draft)===JSON.stringify({heel:saved.heel,toe:saved.toe})?'Ручная: сохранена':'Ручная: черновик'):candidate?.status==='visible'?'Автоматические точки':candidate?'Авто: сомнительные точки':'Авто: точек нет';
 $('details').textContent=manual?'Ручные точки не становятся выходом модели.':candidate?`${data.model}. ${candidate.status==='visible'?'':'Сомнительные точки скрыты по умолчанию. '}${(candidate.reasons||[]).map(reason=>reasons[reason]||'дополнительная проверка модели').join('; ')}`:`${data.model}. Для выбранного ботинка модель не дала ориентиров.`;
 $('editor').hidden=!manual;$('save').disabled=angle(draft?.heel,draft?.toe)===null;
 $('instruction').textContent=`Следующий клик: ${active==='heel'?'пятка':'носок'}. После уточнения сохраните точки.`;
 for(const name of ['heel','toe'])$(name).setAttribute('aria-pressed',String(active===name));
 $('frame').textContent=`Кадр ${frame().frameIndex} · ${index+1} / ${item.frames.length}`;$('slider').value=index;$('prev').disabled=index===0;$('next').disabled=index===item.frames.length-1;
 $('count').textContent=`Сохранено: ${labels.size}`;
}
async function showFrame(nextItem,nextIndex){
 requestedItem=nextItem;requestedIndex=nextIndex;loading=true;
 canvas.setAttribute('aria-busy','true');
 try{
  const committed=await loader.show(nextItem.frames[nextIndex].image,next=>{
   item=nextItem;index=nextIndex;image=next;loading=false;
   canvas.setAttribute('aria-busy','false');
   $('attempt').value=data.items.indexOf(item);
   $('slider').max=item.frames.length-1;
   for(const [id,value] of [['last',item.lastContact],['first',item.firstContact]])$(id).disabled=!item.frames.some(f=>f.frameIndex===value);
   resetDraft();draw();
  });
  if(committed)for(const offset of [1,2,3,-1,-2]){
   const neighbor=nextItem.frames[nextIndex+offset];if(neighbor)loader.preload(neighbor.image);
  }
 }catch(error){
  loading=false;canvas.setAttribute('aria-busy','false');stop();
  requestedItem=item;requestedIndex=index;
  if(item){$('attempt').value=data.items.indexOf(item);draw();}
  status('Не удалось загрузить кадр. Предыдущий кадр сохранён на экране.');
 }
}
function move(n){
 const target=requestedItem||item;
 n=Math.max(0,Math.min(target.frames.length-1,n));
 if(n===requestedIndex)return;
 showFrame(target,n);
}
function choose(initialIndex){
 stop();const target=data.items[Number($('attempt').value)];
 const n=Number.isInteger(initialIndex)?initialIndex:Math.max(0,target.frames.findIndex(f=>f.frameIndex===target.firstContact));
 showFrame(target,n);
}
function save(statusName){if(loading||!item)return;try{const entry={...identity(),status:statusName,heel:statusName==='manual'?draft.heel:null,toe:statusName==='manual'?draft.toe:null};validateImport({schemaVersion:1,labels:[entry]},data);const next=new Map(labels);next.set(keyFor(entry),entry);persist(next);drafts.clear(keyFor(identity()));resetDraft();draw();status('Разметка сохранена в этом браузере.');}catch(error){status(`Не сохранено: ${error.message}`);}}
$('prev').onclick=()=>{stop();move(requestedIndex-1);};$('next').onclick=()=>{stop();move(requestedIndex+1);};$('slider').oninput=()=>{stop();move(Number($('slider').value));};$('attempt').onchange=choose;
$('side').onchange=()=>{stop();resetDraft();draw();};$('mode').onchange=()=>{stop();resetDraft();draw();};$('diagnostic').onchange=draw;$('zoom').onchange=draw;
$('play').onclick=()=>{if(timer)return stop();$('play').textContent='Ⅱ Пауза';timer=setInterval(()=>{if(loading)return;if(!item||index===item.frames.length-1)return stop();move(requestedIndex+1);},1000/(data.fps*.1));};
for(const [id,property] of [['last','lastContact'],['first','firstContact']])$(id).onclick=()=>{stop();move(item.frames.findIndex(f=>f.frameIndex===item[property]));};
for(const name of ['heel','toe'])$(name).onclick=()=>{active=name;draw();};
canvas.onclick=e=>{if(loading||!image||$('mode').value!=='manual')return;stop();const r=canvas.getBoundingClientRect();const point=canvasToSource([(e.clientX-r.left)/r.width*data.width,(e.clientY-r.top)/r.height*data.height],view());if(!point||point[0]>=data.width||point[1]>=data.height)return;draft[active]=point;drafts.set(keyFor(identity()),draft);active=active==='heel'?'toe':'heel';draw();status('Точки изменены. Нажмите «Сохранить точки».');};
$('save').onclick=()=>save('manual');$('unobservable').onclick=()=>save('unobservable');
$('clear').onclick=()=>{if(loading||!item)return;try{const next=new Map(labels);next.delete(keyFor(identity()));persist(next);drafts.clear(keyFor(identity()));resetDraft();draw();status('Ручная разметка выбранного ботинка удалена.');}catch(e){status(`Не удалось удалить: ${e.message}`);}};
$('export').onclick=()=>{const url=URL.createObjectURL(new Blob([exportLabels([...labels.values()])],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='boot-manual-labels-v1.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
$('import').onchange=async e=>{try{const file=e.target.files[0];if(!file)return;const entries=validateImport(JSON.parse(await file.text()),data);const next=mergeLabels(labels,entries);persist(next);resetDraft();draw();status(`Импортировано записей: ${entries.length}`);}catch(error){status(`Импорт отменён целиком: ${error.message}`);}finally{e.target.value='';}};
document.addEventListener('keydown',e=>{if(!data||e.target.matches('input,select,textarea')||e.altKey||e.ctrlKey||e.metaKey)return;if(e.code==='Space'&&!e.target.matches('button,a')){e.preventDefault();$('play').click();return;}if(['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();stop();move(requestedIndex+(e.key==='ArrowLeft'?-1:1));}});
window.addEventListener('beforeunload',e=>{if(drafts.dirty){e.preventDefault();e.returnValue='';}});
try{const response=await fetch('./boot-workbench-data.json');if(!response.ok)throw Error(`HTTP ${response.status}`);data=await response.json();if(data.schemaVersion!==1||!data.items?.length||data.items.some(i=>!i.frames?.length))throw Error('Нет доступных кадров');storage='boot-workbench:v1:'+JSON.stringify(data.items.map(i=>[i.attemptId,i.sourceSha256,i.frames.map(f=>[f.frameIndex,f.sourceFrameSha256]) ]));canvas.width=data.width;canvas.height=data.height;canvas.parentElement.style.aspectRatio=`${data.width}/${data.height}`;for(const [i,entry]of data.items.entries()){const o=document.createElement('option');o.value=i;o.textContent=`${entry.athlete} · ${entry.attemptId}`;$('attempt').append(o);}try{const raw=localStorage.getItem(storage);if(raw)labels=new Map(validateImport(JSON.parse(raw),data).map(e=>[keyFor(e),e]));}catch(error){status(`Сохранённая разметка не загружена: ${error.message}. Экспорт прошлой версии можно импортировать после проверки источников.`);}const selected=selectionFromQuery(location.search,data.items);$('attempt').value=selected.attempt;$('side').value=selected.side;choose(selected.index);}catch(error){status(`Не удалось открыть рабочее место: ${error.message}`);document.querySelectorAll('button,input,select').forEach(el=>el.disabled=true);}
