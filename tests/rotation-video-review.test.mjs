import test from 'node:test';
import assert from 'node:assert/strict';
import {validate, validateAthleteGroups} from '../scripts/rotation-video-review-assets/core.mjs';
test('requires exact video provenance and explicit assessment',()=>{
 const items=[{id:'a',sha256:'123'}];
 assert.deepEqual(validate({schemaVersion:1,labels:[{id:'a',sha256:'123',assessment:'short'}]},items),[{id:'a',sha256:'123',assessment:'short'}]);
 assert.throws(()=>validate({schemaVersion:1,labels:[{id:'a',sha256:'456',assessment:'short'}]},items));
 assert.throws(()=>validate({schemaVersion:1,labels:[{id:'a',sha256:'123',assessment:'unknown'}]},items));
});

test('accepts partial anonymous athlete groups bound to this exact dataset',()=>{
 const items=[{id:'a',sha256:'123'},{id:'b',sha256:'456'}];
 const payload={schemaVersion:1,datasetSha256:'dataset-hash',assignments:[{id:'a',sha256:'123',athleteGroup:' A '}]};
 assert.deepEqual(validateAthleteGroups(payload,items,'dataset-hash'),[{id:'a',sha256:'123',athleteGroup:'A'}]);
});

test('rejects stale, duplicate, unknown, empty or malformed athlete groups',()=>{
 const items=[{id:'a',sha256:'123'},{id:'b',sha256:'456'}];
 const payload=rows=>({schemaVersion:1,datasetSha256:'dataset-hash',assignments:rows});
 assert.throws(()=>validateAthleteGroups(payload([{id:'a',sha256:'123',athleteGroup:'A'}]),items,'different-hash'));
 assert.throws(()=>validateAthleteGroups(payload([{id:'a',sha256:'bad',athleteGroup:'A'}]),items,'dataset-hash'));
 assert.throws(()=>validateAthleteGroups(payload([{id:'a',sha256:'123',athleteGroup:'A'},{id:'a',sha256:'123',athleteGroup:'B'}]),items,'dataset-hash'));
 assert.throws(()=>validateAthleteGroups(payload([{id:'x',sha256:'xxx',athleteGroup:'A'}]),items,'dataset-hash'));
 assert.throws(()=>validateAthleteGroups(payload([{id:'a',sha256:'123',athleteGroup:'  '}]),items,'dataset-hash'));
 assert.throws(()=>validateAthleteGroups(payload([{id:'a',sha256:'123',athleteGroup:'A\nB'}]),items,'dataset-hash'));
});
