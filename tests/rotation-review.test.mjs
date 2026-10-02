import test from 'node:test';
import assert from 'node:assert/strict';
import { mergeAssessments, makeAssessment, restoreAssessments, exportAssessments, validateManifest } from '../scripts/rotation-review-assets/rotation-review-core.mjs';
const item={attemptId:'a1',videoId:'v1',sourceSha256:'a'.repeat(64),lastContact:10,firstContact:30,frames:[{frameIndex:10,time:0.2,image:'frames/a.jpg',sourceFrameSha256:'b'.repeat(64)}]};
const manifest={schemaVersion:1,fps:50,width:1280,height:720,items:[item]};
const draft={rotationAssessment:'unknown',visibility:{takeoff:'uncertain',landing:'not_visible'},notes:'не видно'};
test('explicit unknown review stays unknown and excludes unrelated fields',()=>{const r=makeAssessment(item,{...draft,protocol:'3A<'},'2026-09-22T01:00:00.000Z');assert.equal(r.rotationAssessment,'unknown');assert.equal(r.protocol,undefined);assert.equal(r.notes,'не видно');});
test('rejects unsupported labels, malformed identity and incomplete visibility',()=>{for(const patch of [{rotationAssessment:'clean'},{visibility:{takeoff:'clear'}},{notes:5}])assert.throws(()=>makeAssessment(item,{...draft,...patch}));for(const patch of [{attemptId:''},{videoId:null},{sourceSha256:'invalid'},{lastContact:31}])assert.throws(()=>makeAssessment({...item,...patch},draft));});
test('restore accepts exact provenance only and rejects corrupt payloads',()=>{const r=makeAssessment(item,draft);assert.equal(restoreAssessments(JSON.stringify(exportAssessments([r])),manifest).length,1);for(const patch of [{sourceSha256:'c'.repeat(64)},{videoId:'other'},{lastContact:9},{firstContact:31},{attemptId:'other'},{reviewedAt:undefined}])assert.equal(restoreAssessments(JSON.stringify({schemaVersion:1,kind:'rotation-expert-review',assessments:[{...r,...patch}]}),manifest).length,0);assert.equal(restoreAssessments('broken',manifest).length,0);assert.equal(restoreAssessments('{"assessments":[]}',manifest).length,0);});
test('export includes only passed saved assessments and validates manifest frames',()=>{assert.deepEqual(exportAssessments([]),{schemaVersion:1,kind:'rotation-expert-review',assessments:[]});assert.equal(validateManifest(manifest),manifest);assert.throws(()=>validateManifest({...manifest,items:[item,item]}));assert.throws(()=>validateManifest({...manifest,items:[{...item,frames:[]}]}));assert.throws(()=>validateManifest({...manifest,items:[{...item,frames:[{...item.frames[0],image:'https://example.com/a.jpg'}]}]}));});
test('review timestamps need an explicit timezone accepted by importer',()=>{assert.throws(()=>makeAssessment(item,draft,'2026-09-22T01:00:00'));assert.throws(()=>makeAssessment(item,draft,'2026-02-30T01:00:00Z'));assert.doesNotThrow(()=>makeAssessment(item,draft,'2026-09-22T01:00:00+05:00'));});

test('imported reviews survive partial browser saves and newer edits win',()=>{
 const second={...item,attemptId:'a2'}; const both={...manifest,items:[item,second]};
 const base=makeAssessment(item,draft,'2026-09-22T01:00:00Z');
 const correction=makeAssessment(item,{...draft,rotationAssessment:'apparently_complete'},'2026-09-22T02:00:00Z');
 const other=makeAssessment(second,draft,'2026-09-22T01:00:00Z');
 const imported=JSON.stringify(exportAssessments([correction,other]));
 const result=mergeAssessments(imported,JSON.stringify(exportAssessments([base])),both);
 assert.equal(result.length,2);assert.equal(result.find(r=>r.attemptId==='a1').rotationAssessment,'apparently_complete');
 const newer=makeAssessment(item,{...draft,notes:'new edit'},'2026-09-22T03:00:00Z');
 assert.equal(mergeAssessments(imported,JSON.stringify(exportAssessments([newer])),both).find(r=>r.attemptId==='a1').notes,'new edit');
 assert.equal(mergeAssessments(imported,'broken',both).length,2);
});
