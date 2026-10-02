const object=(v,keys)=>v!==null&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).length===keys.length&&keys.every(k=>Object.hasOwn(v,k));
const string=v=>typeof v==='string'&&v.trim().length>0;
const hash=v=>typeof v==='string'&&/^[a-f0-9]{64}$/i.test(v);
const unit=v=>Number.isFinite(v)&&v>=0&&v<=1;
const positive=v=>Number.isSafeInteger(v)&&v>0;
/** Validate a model proposal, optionally binding it to an indexed source video. Throws on invalid data. */
export function validateAnalysisResult(r,context) {
 const require=(ok,message)=>{if(!ok)throw new Error(message)};
 require(object(r,['schemaVersion','kind','status','videoId','sourceSha256','model','coordinateSpace','frames']),'Invalid proposal fields');
 require(r.schemaVersion===1&&r.kind==='pose2d'&&r.status==='model_proposal','Unsupported proposal type');
 require(string(r.videoId)&&hash(r.sourceSha256),'Invalid video provenance');
 require(object(r.model,['name','version','weightsSha256'])&&string(r.model.name)&&string(r.model.version)&&hash(r.model.weightsSha256),'Invalid model provenance');
 require(object(r.coordinateSpace,['type','width','height'])&&r.coordinateSpace.type==='image-normalized'&&positive(r.coordinateSpace.width)&&positive(r.coordinateSpace.height),'Invalid coordinate space');
 require(Array.isArray(r.frames)&&r.frames.length>0,'Frames required');
 if(context)require(r.videoId===context.videoId&&r.sourceSha256.toLowerCase()===context.sourceSha256.toLowerCase()&&Array.isArray(context.times),'Source mismatch');
 let lastIndex=-1,lastTime=-1;
 for(const f of r.frames){
  require(object(f,['frameIndex','time','landmarks'])&&Number.isSafeInteger(f.frameIndex)&&f.frameIndex>lastIndex&&Number.isFinite(f.time)&&f.time>=0&&f.time>lastTime&&Array.isArray(f.landmarks),'Invalid frame sequence');
  if(context)require(Number.isFinite(context.times[f.frameIndex])&&Math.abs(context.times[f.frameIndex]-f.time)<=.00002,'Frame timestamp mismatch');
  const names=new Set();
  for(const p of f.landmarks){require(object(p,['name','x','y','confidence'])&&string(p.name)&&unit(p.x)&&unit(p.y)&&unit(p.confidence)&&!names.has(p.name),'Invalid landmark');names.add(p.name)}
  lastIndex=f.frameIndex;lastTime=f.time;
 }
 return true;
}
