import {test} from 'node:test';
import assert from 'node:assert/strict';
import {isAxelDraft, axelReviewVideos} from '../shared/axel-review.mjs';

test('Axel review includes protocol Axel drafts and only competition videos with one',()=>{
  const videos=[{id:'01',collection:'personal'},{id:'comp-01',collection:'competition'},{id:'comp-02',collection:'competition'}];
  const episodes=[{videoId:'comp-01',protocolCode:'2A<<'},{videoId:'comp-01',protocolCode:'2Lz'},{videoId:'comp-02',protocolCode:'1A*'},{videoId:'01',protocolCode:'2A'}];
  assert.deepEqual(axelReviewVideos(videos,episodes).map(v=>v.id),['comp-01','comp-02']);
  assert.equal(isAxelDraft(episodes[0]),true);
  assert.equal(isAxelDraft(episodes[1]),false);
});
