export class AnnotationHttpError extends Error {
 constructor(message,status){super(message);this.name='AnnotationHttpError';this.status=status;}
}
export function createAnnotationClient(fetcher=(...args)=>fetch(...args)){
 async function request(url,fallback,options){
  const response=await fetcher(url,options);
  let data;try{data=await response.json();}catch{throw new AnnotationHttpError(fallback,response.status);}
  if(!response.ok)throw new AnnotationHttpError(data?.error||fallback,response.status);
  return data;
 }
 return {
  catalog:()=>request('/api/catalog','Не удалось загрузить каталог видео'),
  frames:id=>request('/api/frames/'+encodeURIComponent(id),'Не удалось загрузить точные кадры'),
  annotations:()=>request('/api/annotations','Не удалось прочитать разметку'),
  save:(revision,episodes)=>request('/api/annotations','Не удалось сохранить разметку',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision,episodes,capabilities:['phase-events-v1']})}),
 };
}
