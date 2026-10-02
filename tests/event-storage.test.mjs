import {test} from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {join} from 'node:path';
import {fixture} from './fixtures.mjs';
import {importLegacy} from '../server/importer.mjs';
import {openStore} from '../server/store.mjs';
const caps=['phase-events-v1'];
const extras={events:{opening:{frameIndex:1,time:.05,uncertaintyFrames:2,source:'manual',review:'confirmed'}},boundaryReview:{start:{uncertaintyFrames:0,review:'confirmed'}}};
async function setup(t){const f=fixture(t);await importLegacy(f.source,f.dest);const s=openStore(f.dest);t.after(()=>s.close());return {...f,s};}
test('events and explicit review survive reopen and are recorded in revision history',async t=>{
 const f=await setup(t);const episode={...f.annotations.episodes[0],...extras};
 f.s.save({revision:12,episodes:[episode],capabilities:caps});
 const second=openStore(f.dest);assert.deepEqual(second.read().episodes[0],episode);second.close();
 const db=new DatabaseSync(join(f.dest,'fs-elem.sqlite'),{readOnly:true});t.after(()=>db.close());
 assert.deepEqual(JSON.parse(db.prepare('SELECT document FROM revisions WHERE revision=13').get().document).episodes[0].events,extras.events);
});
test('legacy clients cannot silently erase extended fields, including by deleting an episode',async t=>{
 const f=await setup(t);f.s.save({revision:12,episodes:[{...f.annotations.episodes[0],...extras}],capabilities:caps});
 for(const episodes of [f.annotations.episodes,[]])assert.throws(()=>f.s.save({revision:13,episodes}),e=>e.status===409);
 assert.equal(f.s.read().revision,13);
 f.s.save({revision:13,episodes:[{...f.s.read().episodes[0],events:{}}],capabilities:caps});
 assert.deepEqual(f.s.read().episodes[0].events,{});
});
