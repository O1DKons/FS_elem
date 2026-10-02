export const key=r=>JSON.stringify([r.attemptId,r.frameIndex,r.sourceSha256,r.sourceFrameSha256]);
export function validateLabels(payload,frames){
 if(payload?.schemaVersion!==1||!Array.isArray(payload.labels))throw Error('Invalid format');
 const allowed=new Set(frames.map(key)),seen=new Set();
 return payload.labels.map(r=>{
  const k=key(r);
  if(!allowed.has(k)||seen.has(k)||!['front','back','side','unclear'].includes(r.facing))throw Error('Invalid frame, duplicate or class');
  seen.add(k);
  return {attemptId:r.attemptId,frameIndex:r.frameIndex,sourceSha256:r.sourceSha256,sourceFrameSha256:r.sourceFrameSha256,facing:r.facing};
 });
}
export function initialLabels(raw,seeds,frames){
 return new Map(validateLabels(raw===null?{schemaVersion:1,labels:seeds}:JSON.parse(raw),frames).map(r=>[key(r),r]));
}
