import {test} from 'node:test';
import assert from 'node:assert/strict';
import {validateEpisode} from '../server/validation.mjs';
const times=Array.from({length:20},(_,i)=>i*.05),catalog=[{id:'v',duration:1}];
const base={id:'e',videoId:'v',start:times[5],end:times[13],startFrame:5,endFrame:13,note:'',attemptGroup:''};
const mark=(i,extra={})=>({frameIndex:i,time:times[i],uncertaintyFrames:0,source:'manual',review:'unreviewed',...extra});
const check=e=>validateEpisode(e,catalog,{v:times});
test('legacy episodes and partial events remain valid, including last contact on zero',()=>{
 assert.equal(check(base),true);
 assert.equal(check({...base,events:{lastContact:mark(0),groupingStart:mark(3),groupingComplete:mark(4),opening:mark(10),exitStable:mark(18)}}),true);
});
test('event validation rejects missing, fractional and inconsistent frames and model provenance',()=>{
 for(const patch of [{frameIndex:20},{frameIndex:-1},{frameIndex:1.5},{time:.333},{uncertaintyFrames:-1},{uncertaintyFrames:31},{uncertaintyFrames:1.2},{source:'model'},{review:'expert'},{frameIndex:null},{time:NaN}])
 assert.throws(()=>check({...base,events:{opening:mark(10,patch)}}),JSON.stringify(patch));
 for(const events of [null,[],{unknown:mark(2)},{opening:null}])assert.throws(()=>check({...base,events}));
});
test('chronology applies to available events without inventing missing phases',()=>{
 for(const events of [{lastContact:mark(5)},{groupingStart:mark(8),groupingComplete:mark(7)},{groupingStart:mark(11),opening:mark(9)},{opening:mark(14)},{exitStable:mark(12)}])assert.throws(()=>check({...base,events}));
 assert.equal(check({...base,events:{opening:mark(13),exitStable:mark(13)}}),true);
});
test('boundary review requires a marked boundary and valid uncertainty/review state',()=>{
 assert.equal(check({...base,boundaryReview:{start:{uncertaintyFrames:2,review:'confirmed'}}}),true);
 for(const boundaryReview of [{start:{uncertaintyFrames:-1,review:'confirmed'}},{end:{uncertaintyFrames:1,review:'model'}},{unknown:{uncertaintyFrames:0,review:'confirmed'}}])assert.throws(()=>check({...base,boundaryReview}));
 assert.throws(()=>check({...base,start:null,startFrame:null,boundaryReview:{start:{uncertaintyFrames:0,review:'confirmed'}}}));
});
