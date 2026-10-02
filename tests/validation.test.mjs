import {test} from 'node:test';
import assert from 'node:assert/strict';
import {validateEpisode,validateDocument} from '../server/validation.mjs';
const catalog=[{id:'v',duration:1,frameCount:4}];
const frames={v:[0,.03,.07,.11]};
const valid={id:'e',videoId:'v',start:0,end:.07,startFrame:0,endFrame:2,note:'',attemptGroup:''};
test('zero frame and incomplete drafts remain editable',()=>{
 assert.equal(validateEpisode(valid,catalog,frames),true);
 assert.equal(validateEpisode({...valid,end:null,endFrame:null},catalog,frames),true);
 assert.equal(validateEpisode({...valid,start:null,end:null,startFrame:null,endFrame:null},catalog,frames),true);
});
test('rejects invalid indices and time/frame disagreements',()=>{
 for(const patch of [{startFrame:-1},{endFrame:4},{endFrame:1.5},{endFrame:'2'},{start:.02},{endFrame:null},{start:null},{end:.03,endFrame:2},{startFrame:undefined}])
  assert.throws(()=>validateEpisode({...valid,...patch},catalog,frames),JSON.stringify(patch));
});
test('rejects malformed identity, groups, notes and boundaries',()=>{
 for(const patch of [{id:''},{id:2},{videoId:'other'},{attemptGroup:{}},{attemptGroup:1},{note:{}},{end:NaN},{end:2},{start:.07,startFrame:2},{note:'a'.repeat(5001)}])
  assert.throws(()=>validateEpisode({...valid,...patch},catalog,frames));
});
test('save documents reject malformed revision, duplicate IDs and wrong schema',()=>{
 for(const revision of [-1,1.1,'1',null,undefined,Number.MAX_SAFE_INTEGER+1])
  assert.throws(()=>validateDocument({revision,episodes:[valid]},catalog,frames));
 assert.throws(()=>validateDocument({revision:0,episodes:[valid,valid]},catalog,frames));
 assert.throws(()=>validateDocument({revision:0,schemaVersion:7,episodes:[valid]},catalog,frames));
 assert.equal(validateDocument({revision:0,episodes:[valid]},catalog,frames),true);
});
test('legacy rounded container duration does not invalidate the final decoded frame',()=>{
 const c=[{id:'v',duration:.10,frameCount:4}];const f={v:[0,.03,.07,.1035]};
 assert.equal(validateEpisode({...valid,end:.1035,endFrame:3},c,f),true);
});
