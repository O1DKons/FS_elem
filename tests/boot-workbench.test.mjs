import test from 'node:test';
import assert from 'node:assert/strict';
import {angle, circularDifference, keyFor, validateImport, exportLabels} from '../scripts/boot-workbench-assets/boot-workbench-core.mjs';
const manifest={schemaVersion:1,width:1280,height:720,items:[{attemptId:'a',sourceSha256:'video',frames:[{frameIndex:1,sourceFrameSha256:'image'}]}]};
const entry={attemptId:'a',sourceSha256:'video',frameIndex:1,sourceFrameSha256:'image',side:'left',status:'manual',heel:[10,20],toe:[20,20]};
test('angles require two distinct finite points and wrap across ±180',()=>{assert.equal(angle(null,[1,1]),null);assert.equal(angle([1,1],[1,1]),null);assert.equal(angle([0,0],[1,0]),0);assert.equal(angle([0,0],[0,1]),90);assert.equal(circularDifference(179,-179),-2);});
test('export restores labels with provenance and collision-free identity',()=>{const restored=validateImport(JSON.parse(exportLabels([entry])),manifest);assert.deepEqual(restored,[entry]);assert.notEqual(keyFor(entry),keyFor({...entry,side:'right'}));assert.notEqual(keyFor(entry),keyFor({...entry,sourceSha256:'new'}));});
test('import rejects whole batch on bad provenance geometry labels or duplicate entries',()=>{for(const patch of [{sourceFrameSha256:'wrong'},{sourceSha256:'wrong'},{side:'both'},{status:'auto'},{heel:[-1,0]},{toe:[1281,0]},{toe:[1280,0]},{toe:[0,720]},{toe:[NaN,0]},{toe:null},{frameIndex:2}]) assert.throws(()=>validateImport({schemaVersion:1,labels:[{...entry,...patch}]},manifest));assert.throws(()=>validateImport({schemaVersion:1,labels:[entry,entry]},manifest));assert.throws(()=>validateImport({schemaVersion:2,labels:[]},manifest));});
test('unobservable labels must contain no invented geometry',()=>{const hidden={...entry,status:'unobservable',heel:null,toe:null};assert.deepEqual(validateImport({schemaVersion:1,labels:[hidden]},manifest),[hidden]);assert.throws(()=>validateImport({schemaVersion:1,labels:[{...hidden,toe:[1,2]}]},manifest));});

test('drafts survive navigation and clean independently after save or remove',async()=>{const {Drafts}=await import('../scripts/boot-workbench-assets/boot-workbench-core.mjs');const drafts=new Drafts();drafts.set('a',{heel:[1,2],toe:null});drafts.set('b',{heel:[3,4],toe:[5,6]});assert.deepEqual(drafts.get('a'),{heel:[1,2],toe:null});drafts.clear('a');assert.equal(drafts.get('a'),undefined);assert.equal(drafts.dirty,true);drafts.clear('b');assert.equal(drafts.dirty,false);});
test('crop mapping preserves source coordinates and ignores letterbox',async()=>{const {viewTransform,canvasToSource,sourceToCanvas}=await import('../scripts/boot-workbench-assets/boot-workbench-core.mjs');const view=viewTransform([100,200,500,400],1280,720);assert.deepEqual(sourceToCanvas([100,200],view),[0,40]);assert.deepEqual(sourceToCanvas([500,400],view),[1280,680]);assert.deepEqual(canvasToSource([1280,680],view),[500,400]);assert.deepEqual(canvasToSource([640,360],view),[300,300]);assert.equal(canvasToSource([640,20],view),null);});
test('import merges exact duplicates idempotently and conflicting batch atomically',async()=>{const {mergeLabels}=await import('../scripts/boot-workbench-assets/boot-workbench-core.mjs');const current=new Map([[keyFor(entry),entry]]);assert.equal(mergeLabels(current,[entry]).size,1);assert.throws(()=>mergeLabels(current,[{...entry,side:'right'},{...entry,toe:[40,30]}]));assert.equal(current.size,1);assert.deepEqual(current.get(keyFor(entry)),entry);});
test('query selection accepts only existing attempts frames and valid sides',async()=>{const {selectionFromQuery}=await import('../scripts/boot-workbench-assets/boot-workbench-core.mjs');const items=[{attemptId:'a',firstContact:20,frames:[{frameIndex:10},{frameIndex:20}]}];assert.deepEqual(selectionFromQuery('?attempt=a&frame=10&side=left',items),{attempt:0,index:0,side:'left'});assert.deepEqual(selectionFromQuery('?attempt=bad&frame=999&side=bad',items),{attempt:0,index:1,side:'landing'});assert.deepEqual(selectionFromQuery('',items),{attempt:0,index:1,side:'landing'});});

test('landing candidate labels retain separate identity and restore in v1',()=>{const landing={...entry,side:'landing'};assert.deepEqual(validateImport({schemaVersion:1,labels:[landing]},manifest),[landing]);assert.notEqual(keyFor(landing),keyFor(entry));});
test('focus crop follows automatic midpoint with fixed size and clamps source bounds',async()=>{const {focusCrop}=await import('../scripts/boot-workbench-assets/boot-workbench-core.mjs');assert.deepEqual(focusCrop({heel:[10,10],toe:[20,20]},1280,720),[0,0,280,200]);assert.deepEqual(focusCrop({heel:[1250,700],toe:[1270,710]},1280,720),[1000,520,1280,720]);assert.deepEqual(focusCrop({heel:[500,400],toe:[600,400]},1280,720),[410,300,690,500]);assert.equal(focusCrop({heel:null,toe:[20,20]},1280,720),null);});

test('frame loader keeps displayed frame until latest image resolves and ignores stale loads',async()=>{
 const {FrameLoader}=await import('../scripts/boot-workbench-assets/boot-workbench-core.mjs');
 const pending=new Map(), commits=[];
 const loader=new FrameLoader(src=>new Promise((resolve,reject)=>pending.set(src,{resolve,reject})),2);
 const a=loader.show('a',image=>commits.push(image)); const b=loader.show('b',image=>commits.push(image));
 assert.deepEqual(commits,[]);
 pending.get('b').resolve('B');await b;
 pending.get('a').resolve('A');await a;assert.deepEqual(commits,['B']);
 const bad=loader.show('bad',image=>commits.push(image));pending.get('bad').reject(Error('missing'));
 await assert.rejects(bad);assert.deepEqual(commits,['B']);
 await loader.show('b',image=>commits.push(image));assert.deepEqual(commits,['B','B']);
 assert.ok(loader.cache.size<=2);
});

test('landing trace uses accepted auto geometry, keeps gaps and wraps contact delta',async()=>{
 const {landingTrace}=await import('../scripts/boot-workbench-assets/boot-workbench-core.mjs');
 const row=(n,degrees,status='visible')=>({frameIndex:n,candidates:[{side:'landing',status,heel:[0,0],toe:[Math.cos(degrees*Math.PI/180),Math.sin(degrees*Math.PI/180)]}]});
 const item={firstContact:10,frames:[row(9,170),row(10,179),row(11,-179),row(12,30,'uncertain'),row(13,-170)]};
 const trace=landingTrace(item,'landing',50);
 assert.equal(trace[0].seconds,-.02);
 assert.ok(Math.abs(trace[2].delta-2)<1e-8);
 assert.equal(trace[3].heading,null);assert.equal(trace[3].delta,null);
 assert.ok(Math.abs(trace[4].delta-11)<1e-8);
 item.frames[1].candidates[0].status='uncertain';
 assert.ok(landingTrace(item,'landing',50).every(p=>p.delta===null));
});
