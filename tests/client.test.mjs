import test from 'node:test';
import assert from 'node:assert/strict';
const http = await import('../apps/web/lib/annotation-client.mjs').catch(()=>({}));
const persistence = await import('../apps/web/lib/annotation-persistence.mjs').catch(()=>({}));
test('HTTP rejects catalog and frame failures with useful messages', async()=>{
 assert.equal(typeof http.createAnnotationClient,'function');
 const client=http.createAnnotationClient(async()=>new Response('unavailable',{status:503}));
 await assert.rejects(client.catalog(),/каталог/); await assert.rejects(client.frames('01'),/кадры/);
});
test('HTTP exposes conflict status and sends capabilities',async()=>{
 assert.equal(typeof http.createAnnotationClient,'function');
 let payload;const client=http.createAnnotationClient(async(url,options)=>{payload=JSON.parse(options.body);return Response.json({error:'Конфликт ревизии'},{status:409});});
 await assert.rejects(client.save(4,[]),e=>e.status===409&&e.message==='Конфликт ревизии');
 assert.deepEqual(payload,{revision:4,episodes:[],capabilities:['phase-events-v1']});
});
test('persistence serializes snapshots and advances only acknowledged revisions',async()=>{
 assert.equal(typeof persistence.createAnnotationPersistence,'function');
 const calls=[];let finish; const states=[];
 const p=persistence.createAnnotationPersistence({revision:7,save:async(revision,episodes)=>{calls.push({revision,episodes});if(calls.length===1)await new Promise(r=>finish=r);return {revision:revision+1};},onState:s=>states.push(s)});
 p.enqueue(['first']);p.enqueue(['latest']);assert.equal(calls.length,1);finish();await p.idle();
 assert.deepEqual(calls,[{revision:7,episodes:['first']},{revision:8,episodes:['latest']}]);assert.equal(p.revision,9);assert.equal(states.at(-1).saving,false);
});
test('failure pauses pending writes and retry saves latest local snapshot at unchanged revision',async()=>{
 assert.equal(typeof persistence.createAnnotationPersistence,'function');
 const calls=[];let fail;const p=persistence.createAnnotationPersistence({revision:2,save:async(revision,episodes)=>{calls.push({revision,episodes});if(calls.length===1)await new Promise((_,reject)=>fail=reject);return {revision:3};}});
 p.enqueue(['old']);p.enqueue(['new']);fail(new Error('409 conflict'));await p.idle();assert.equal(p.revision,2);assert.equal(p.failed,true);assert.equal(calls.length,1);
 p.enqueue(['newest']);await p.idle();assert.equal(calls.length,1);p.retry(['newest']);await p.idle();assert.deepEqual(calls[1],{revision:2,episodes:['newest']});assert.equal(p.failed,false);assert.equal(p.revision,3);
});
test('HTTP reads successful catalog, frame and annotation responses',async()=>{
 const data={'/api/catalog':[{id:'01'}],'/api/frames/01':[0,0.04],'/api/annotations':{revision:6,episodes:[]}};
 const client=http.createAnnotationClient(async url=>Response.json(data[url]));
 assert.deepEqual(await client.catalog(),data['/api/catalog']);assert.deepEqual(await client.frames('01'),[0,0.04]);assert.deepEqual(await client.annotations(),{revision:6,episodes:[]});
});
test('HTTP does not treat malformed success bodies or failed annotation reads as loaded data',async()=>{
 const malformed=http.createAnnotationClient(async()=>new Response('invalid',{status:200}));
 await assert.rejects(malformed.annotations(),/прочитать разметку/);
 const unavailable=http.createAnnotationClient(async()=>Response.json({error:'Database unavailable'},{status:500}));
 await assert.rejects(unavailable.annotations(),e=>e.status===500&&e.message==='Database unavailable');
});
test('only acknowledged snapshots trigger saved callback; failed latest edits remain pending',async()=>{
 const acknowledged=[];let attempt=0;
 const p=persistence.createAnnotationPersistence({revision:0,save:async()=>{if(++attempt===2)throw Error('offline');return {revision:attempt};},onSaved:(snapshot,revision)=>acknowledged.push({snapshot,revision})});
 p.enqueue(['saved']);await p.idle();p.enqueue(['local']);await p.idle();
 assert.deepEqual(acknowledged,[{snapshot:['saved'],revision:1}]);assert.equal(p.failed,true);assert.equal(p.revision,1);
});
