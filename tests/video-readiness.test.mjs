import {test} from 'node:test';
import assert from 'node:assert/strict';
import {observeVideoReadiness} from '../apps/web/lib/video-readiness.mjs';
test('already loaded video enables controls when hydration attaches late',()=>{
 const video=new EventTarget();video.readyState=4;const states=[];
 const dispose=observeVideoReadiness(video,x=>states.push(x));assert.deepEqual(states,[true]);dispose();
});
test('metadata loading updates controls and disposal prevents stale video events',()=>{
 const video=new EventTarget();video.readyState=0;const states=[];
 const dispose=observeVideoReadiness(video,x=>states.push(x));video.readyState=1;video.dispatchEvent(new Event('loadedmetadata'));dispose();video.readyState=0;video.dispatchEvent(new Event('loadedmetadata'));
 assert.deepEqual(states,[false,true]);
});
