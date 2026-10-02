import {test} from 'node:test';
import assert from 'node:assert/strict';
import {existsSync,readFileSync,writeFileSync,symlinkSync} from 'node:fs';
import {join} from 'node:path';
import {DatabaseSync} from 'node:sqlite';
import {fixture} from './fixtures.mjs';
import {importLegacy} from '../server/importer.mjs';
import {openStore} from '../server/store.mjs';
test('dry run has no side effects; import preserves metadata, labels, revision and media',async t=>{
 const f=fixture(t);const before=readFileSync(join(f.source,'jump-marker/data/annotations.json'));
 const dry=await importLegacy(f.source,f.dest,{dryRun:true});assert.equal(dry.videos,1);assert.equal(existsSync(f.dest),false);
 const result=await importLegacy(f.source,f.dest);assert.equal(result.episodes,1);assert.equal(result.labels,1);
 const store=openStore(f.dest);t.after(()=>store.close());
 assert.deepEqual(store.catalog(),f.catalog);assert.deepEqual(store.read().episodes,f.annotations.episodes);assert.equal(store.read().revision,12);assert.equal(store.read().schemaVersion,2);
 assert.deepEqual(store.frames('01'),[0,.05,.1,.15]);assert.deepEqual(readFileSync(store.media('01')),f.media);
 const db=new DatabaseSync(join(f.dest,'fs-elem.sqlite'),{readOnly:true});
 const label=db.prepare('SELECT * FROM expert_labels').get();assert.equal(label.attempt_id,null);assert.equal(JSON.parse(label.payload).underrotation,'none_stated');assert.equal(JSON.parse(label.provenance).scope,f.expert.scope);db.close();
 assert.deepEqual(readFileSync(join(f.source,'jump-marker/data/annotations.json')),before);
});
test('reimport is idempotent and never resets later annotations',async t=>{
 const f=fixture(t);await importLegacy(f.source,f.dest);
 const store=openStore(f.dest);store.save({revision:12,episodes:[{...f.annotations.episodes[0],note:'edited'}]});store.close();
 assert.equal((await importLegacy(f.source,f.dest)).status,'already_imported');
 const reopened=openStore(f.dest);t.after(()=>reopened.close());assert.equal(reopened.read().revision,13);assert.equal(reopened.read().episodes[0].note,'edited');
});
test('bad checksums and invalid frames cannot publish data',async t=>{
 const f=fixture(t);writeFileSync(join(f.source,'axel-15/sample.mp4'),'corrupt');
 await assert.rejects(importLegacy(f.source,f.dest),/checksum/i);assert.equal(existsSync(f.dest),false);
 writeFileSync(join(f.source,'axel-15/sample.mp4'),f.media);f.annotations.episodes[0].endFrame=99;f.json('jump-marker/data/annotations.json',f.annotations);
 await assert.rejects(importLegacy(f.source,f.dest));assert.equal(existsSync(f.dest),false);
});
test('changed source cannot overwrite an existing import',async t=>{
 const f=fixture(t);await importLegacy(f.source,f.dest);f.annotations.revision=13;f.json('jump-marker/data/annotations.json',f.annotations);
 await assert.rejects(importLegacy(f.source,f.dest),/already|different/i);
});
test('store rejects stale revisions and invalid updates without losing saved data',async t=>{
 const f=fixture(t);await importLegacy(f.source,f.dest);const s=openStore(f.dest);t.after(()=>s.close());
 assert.throws(()=>s.save({revision:11,episodes:[]}),e=>e.status===409);
 assert.throws(()=>s.save({revision:12,episodes:[{...f.annotations.episodes[0],startFrame:-1}]}));
 assert.equal(s.read().revision,12);assert.equal(s.read().episodes.length,1);
 const second=openStore(f.dest);t.after(()=>second.close());s.save({revision:12,episodes:[]});assert.throws(()=>second.save({revision:12,episodes:f.annotations.episodes}),e=>e.status===409);
 assert.equal(s.read().revision,13);assert.deepEqual(s.read().episodes,[]);
});

test('a symlink cannot redirect publication into the original source',async t=>{
 const f=fixture(t);const alias=join(f.root,'alias');symlinkSync(f.source,alias,'dir');
 await assert.rejects(importLegacy(f.source,join(alias,'new-data')),/separate/i);
 assert.equal(existsSync(join(f.source,'new-data')),false);
});
test('case-only video IDs are rejected on every platform before copying',async t=>{
 const f=fixture(t);f.json('jump-marker/catalog.json',[{...f.catalog[0],id:'a'},{...f.catalog[0],id:'A'}]);
 f.json('jump-marker/frames/a.json',[0,.05,.1,.15]);f.json('jump-marker/frames/A.json',[0,.05,.1,.15]);
 f.annotations.episodes[0].videoId='a';f.json('jump-marker/data/annotations.json',f.annotations);f.expert.labels[0].videoId='a';f.json('ssd-personal-videos/expert-element-labels.json',f.expert);
 await assert.rejects(importLegacy(f.source,f.dest),/ID|collision/i);assert.equal(existsSync(f.dest),false);
});
