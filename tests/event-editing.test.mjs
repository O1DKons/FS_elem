import {test} from 'node:test';
import assert from 'node:assert/strict';
import {markEvent,markBoundary} from '../shared/event-editing.mjs';
const times=[0,.04,.08,.12];
test('moving a confirmed event resets confirmation and retains uncertainty',()=>{
 const e={events:{opening:{frameIndex:1,time:.04,uncertaintyFrames:2,source:'manual',review:'confirmed'}}};
 const next=markEvent(e,'opening',2,times);
 assert.equal(next.events.opening.review,'unreviewed');assert.equal(next.events.opening.uncertaintyFrames,2);assert.equal(next.events.opening.time,.08);assert.equal(e.events.opening.frameIndex,1);
});
test('moving a boundary resets only that boundary review',()=>{
 const e={start:0,startFrame:0,boundaryReview:{start:{uncertaintyFrames:1,review:'confirmed'},end:{uncertaintyFrames:0,review:'confirmed'}}};
 const next=markBoundary(e,'start',1,times);assert.equal(next.start,.04);assert.equal(next.boundaryReview.start.review,'unreviewed');assert.equal(next.boundaryReview.end.review,'confirmed');
});
