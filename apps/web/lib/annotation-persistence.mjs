/** Serial writer: a failed write never advances the revision or discards local data. */
export function createAnnotationPersistence({revision:initialRevision,save,onState=()=>{},onSaved=()=>{}}){
 let revision=initialRevision,pending=null,running=null,failed=false,error=null;
 const publish=saving=>onState({saving,failed,error,revision});
 async function drain(){
  publish(true);
  while(pending!==null&&!failed){
   const snapshot=pending;pending=null;
   try{const result=await save(revision,snapshot);revision=result.revision;onSaved(snapshot,revision);}
   catch(cause){failed=true;error=cause;if(pending===null)pending=snapshot;}
  }
 }
 function start(){
  if(running||failed||pending===null)return;
  running=drain().finally(()=>{running=null;publish(false);if(pending!==null&&!failed)start();});
 }
 return {
  get revision(){return revision;},get failed(){return failed;},
  enqueue(snapshot){pending=snapshot;start();},
  retry(snapshot){pending=snapshot;failed=false;error=null;start();},
  async idle(){while(running)await running;},
 };
}
