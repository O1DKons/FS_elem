export const AXELS=new Set(['1A','2A','3A']);
export function validate(payload,items,datasetSha256){
 if(payload?.schemaVersion!==1||payload.datasetSha256!==datasetSha256||!Array.isArray(payload.labels))throw Error('Неверный формат или другой набор видео');
 const known=new Map(items.map(i=>[i.id,i.sha256])),seen=new Set();
 return payload.labels.map(r=>{
  if(!r||!known.has(r.id)||known.get(r.id)!==r.sha256||seen.has(r.id))throw Error('Неизвестное, повторное или изменённое видео');
  if(!['1A','2A','3A','other','unclear'].includes(r.element))throw Error('Выберите элемент');
  if(AXELS.has(r.element)?!['complete','short','unclear'].includes(r.rotation):r.rotation!==null)throw Error('Для акселя нужна оценка докрута; для остальных она должна отсутствовать');
  if(r.athleteGroup!==null&&typeof r.athleteGroup!=='string')throw Error('Неверный код спортсмена');
  if(typeof r.athleteGroup==='string'&&/[\x00-\x1f]/.test(r.athleteGroup))throw Error('Код спортсмена содержит управляющие символы');
  const group=r.athleteGroup===null?null:r.athleteGroup.trim()||null;
  if(group?.length>64)throw Error('Код спортсмена слишком длинный');
  seen.add(r.id);return{id:r.id,sha256:r.sha256,element:r.element,rotation:r.rotation,athleteGroup:group};
 });
}
