const point = p => Array.isArray(p) && p.length === 2 && p.every(Number.isFinite);
export function angle(heel, toe) {
  if (!point(heel) || !point(toe) || heel.every((n,i)=>n===toe[i])) return null;
  return Math.atan2(toe[1]-heel[1],toe[0]-heel[0])*180/Math.PI;
}
export const circularDifference = (a,b) => ((a-b+180)%360+360)%360-180;
export const keyFor = e => JSON.stringify([e.sourceSha256,e.attemptId,e.frameIndex,e.sourceFrameSha256,e.side]);
export const exportLabels = labels => JSON.stringify({schemaVersion:1,labels},null,2);
export function validateImport(payload, manifest) {
  if (payload?.schemaVersion !== 1 || !Array.isArray(payload.labels)) throw Error('Неподдерживаемый формат разметки');
  const seen = new Set();
  return payload.labels.map(e => {
    const item = manifest.items.find(i=>i.attemptId===e?.attemptId && i.sourceSha256===e.sourceSha256);
    const frame = item?.frames.find(f=>f.frameIndex===e.frameIndex && f.sourceFrameSha256===e.sourceFrameSha256);
    if (!frame || !['landing','left','right'].includes(e.side) || !['manual','unobservable'].includes(e.status)) throw Error('Разметка не соответствует исходному видео, кадру или стороне');
    if (e.status==='manual' ? ![e.heel,e.toe].every(p=>point(p) && p[0]>=0 && p[0]<manifest.width && p[1]>=0 && p[1]<manifest.height) || angle(e.heel,e.toe)===null : e.heel!==null || e.toe!==null) throw Error('Некорректные координаты разметки');
    const key=keyFor(e); if(seen.has(key)) throw Error('Повторная разметка одного кадра и ботинка'); seen.add(key);
    return {attemptId:e.attemptId,sourceSha256:e.sourceSha256,frameIndex:e.frameIndex,sourceFrameSha256:e.sourceFrameSha256,side:e.side,status:e.status,heel:e.heel,toe:e.toe};
  });
}

export class Drafts {
  #entries = new Map();
  set(key, value) { this.#entries.set(key, structuredClone(value)); }
  get(key) { const value = this.#entries.get(key); return value && structuredClone(value); }
  clear(key) { this.#entries.delete(key); }
  get dirty() { return this.#entries.size > 0; }
}
export function viewTransform(crop, width, height) {
  const [x0,y0,x1,y1]=crop;
  const scale=Math.min(width/(x1-x0),height/(y1-y0));
  return {x0,y0,x1,y1,scale,dx:(width-(x1-x0)*scale)/2,dy:(height-(y1-y0)*scale)/2};
}
export const sourceToCanvas = ([x,y],v) => [v.dx+(x-v.x0)*v.scale,v.dy+(y-v.y0)*v.scale];
export function canvasToSource([x,y],v) {
  const point=[(x-v.dx)/v.scale+v.x0,(y-v.dy)/v.scale+v.y0];
  return point[0]<v.x0 || point[0]>v.x1 || point[1]<v.y0 || point[1]>v.y1 ? null : point;
}
export function mergeLabels(existing, entries) {
  const next=new Map(existing);
  const same=(a,b)=>a.status===b.status && JSON.stringify(a.heel)===JSON.stringify(b.heel) && JSON.stringify(a.toe)===JSON.stringify(b.toe);
  for(const entry of entries){const key=keyFor(entry);if(next.has(key)&&!same(next.get(key),entry))throw Error('Конфликт с существующей разметкой этого кадра и ботинка');next.set(key,entry);}
  return next;
}
export function selectionFromQuery(query,items) {
  const params=new URLSearchParams(query);
  const attempt=Math.max(0,items.findIndex(i=>i.attemptId===params.get('attempt')));
  const item=items[attempt];
  const requested=params.get('frame');
  const requestedIndex=requested!==null&&/^\d+$/.test(requested)?item.frames.findIndex(f=>f.frameIndex===Number(requested)):-1;
  return {attempt,index:requestedIndex>=0?requestedIndex:Math.max(0,item.frames.findIndex(f=>f.frameIndex===item.firstContact)),side:['landing','left','right'].includes(params.get('side'))?params.get('side'):'landing'};
}
export function focusCrop(candidate,width,height) {
  if(!candidate || ![candidate.heel,candidate.toe].every(p=>point(p)&&p[0]>=0&&p[0]<width&&p[1]>=0&&p[1]<height))return null;
  const w=Math.min(280,width),h=Math.min(200,height);
  const x=Math.max(0,Math.min(width-w,(candidate.heel[0]+candidate.toe[0])/2-w/2));
  const y=Math.max(0,Math.min(height-h,(candidate.heel[1]+candidate.toe[1])/2-h/2));
  return [x,y,x+w,y+h];
}

// Decode before committing; pending and failed requests never clear the displayed frame.
export class FrameLoader {
 constructor(load,limit=16){this.load=load;this.limit=limit;this.cache=new Map();this.token=0;}
 get(src){
  if(this.cache.has(src)){const value=this.cache.get(src);this.cache.delete(src);this.cache.set(src,value);return value;}
  const promise=this.load(src);this.cache.set(src,promise);
  promise.catch(()=>{if(this.cache.get(src)===promise)this.cache.delete(src);});
  while(this.cache.size>this.limit)this.cache.delete(this.cache.keys().next().value);
  return promise;
 }
 async show(src,commit){
  const token=++this.token;
  try{const image=await this.get(src);if(token===this.token){commit(image);return true;}return false;}
  catch(error){if(token===this.token)throw error;return false;}
 }
 preload(src){this.get(src).catch(()=>{});}
}

export function landingTrace(item,side,fps){
 if(!Number.isFinite(fps)||fps<=0)throw Error('Invalid frame rate');
 const rows=item.frames.map(f=>{
  const c=f.candidates?.find(c=>c.side===side);
  return {frameIndex:f.frameIndex,seconds:(f.frameIndex-item.firstContact)/fps,
   heading:c?.status==='visible'?angle(c.heel,c.toe):null};
 });
 const reference=rows.find(r=>r.frameIndex===item.firstContact)?.heading;
 return rows.map(r=>({...r,delta:r.heading!=null&&reference!=null?circularDifference(r.heading,reference):null}));
}
