import test from 'node:test';
import assert from 'node:assert/strict';
import {validateLabels} from '../scripts/facing-review-assets/facing-core.mjs';
const row={attemptId:'a',frameIndex:10,sourceSha256:'v',sourceFrameSha256:'f'};
test('review validates exact frame provenance and explicit classes',()=>{
 const entry={...row,facing:'back'};
 assert.deepEqual(validateLabels({schemaVersion:1,labels:[entry]},[row]),[entry]);
 for(const patch of [{facing:'unknown'},{sourceFrameSha256:'bad'},{frameIndex:11}])
  assert.throws(()=>validateLabels({schemaVersion:1,labels:[{...entry,...patch}]},[row]));
 assert.throws(()=>validateLabels({schemaVersion:1,labels:[entry,entry]},[row]));
});
test('unreviewed frames are not assigned an automatic class',()=>{
 assert.deepEqual(validateLabels({schemaVersion:1,labels:[]},[row]),[]);
});
test('expanded review restores expert seeds once and preserves later removals',async()=>{
 const {initialLabels}=await import('../scripts/facing-review-assets/facing-core.mjs');
 const seed={...row,facing:'front'};
 assert.equal(initialLabels(null,[seed],[row]).size,1);
 assert.equal(initialLabels(JSON.stringify({schemaVersion:1,labels:[]}),[seed],[row]).size,0);
 assert.throws(()=>initialLabels(null,[{...seed,sourceSha256:'wrong'}],[row]));
});
