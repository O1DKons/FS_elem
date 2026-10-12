// Prepared only. No module/test/native execution in the Source preparation scope.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {requireMacDesktopReady,validateRecipeBinding,expectedMacRecipe} from '../../scripts/macos-bundle.mjs';

test('online or stale runtime headers cannot reuse a Mac offline receipt',()=>{
  for(const delta of [{offline:false},{packageVersion:'0.2.5'},{pythonVersions:{science:'3.12.16',pose:'3.9.20'}}]){
    const root=fs.mkdtempSync(path.join(os.tmpdir(),'FS_elem offline-header-'));
    try{
      const app=path.join(root,'app'),user=path.join(root,'user');fs.mkdirSync(app);fs.mkdirSync(user);
      fs.writeFileSync(path.join(app,'macOS-bundle.json'),JSON.stringify({
        schemaVersion:1,packageVersion:'0.2.6',platformId:'macos-arm64',offline:true,
        pythonVersions:{science:'3.12.15',pose:'3.9.20'},...delta}));
      assert.throws(()=>requireMacDesktopReady(app,user),/Unsupported Mac package/);
    }finally{fs.rmSync(root,{recursive:true,force:true});}
  }
});
function fixture(){
  const rule={status:'source-accepted',
    parent:{path:'configs/axel-release-offline-macos-arm64-parent-v026.json',bytes:1,sha256:'1'.repeat(64)},
    derived:{path:'configs/axel-release-ort4-macos-app.json',bytes:2,sha256:'2'.repeat(64)},
    modelManifest:{path:'assets/models/manifest-offline-macos-v026.json',bytes:3,sha256:'3'.repeat(64)},
    sourceUpdates:[{path:'runtime/pipeline/support.py',key:'../runtime/pipeline/support.py',bytes:4,sha256:'4'.repeat(64)}],
    packagingProvenance:{scope:'fixture'}};
  const expected=new Map([...['parent','derived','modelManifest'].map(k=>[rule[k].path,rule[k]]),
                          [rule.sourceUpdates[0].path,rule.sourceUpdates[0]]]);
  const original={inputSha256:{'../runtime/pipeline/support.py':'0'.repeat(64)},
    backendSourceProvenance:{runtimeHashes:{'../runtime/pipeline/support.py':'0'.repeat(64)},runtimeBytes:{'../runtime/pipeline/support.py':9}},
    sampleFps:8.333333,ortThreads:{intraOpNumThreads:4,interOpNumThreads:1},models:{flight:{sha256:'a'.repeat(64)}}};
  return {rule,expected,original};
}
test('Root descriptor must match inventory and cannot duplicate or escape Source rows',()=>{
  const {rule,expected}=fixture();assert.equal(validateRecipeBinding(rule,expected),rule);
  for(const mutate of [
    r=>r.sourceUpdates.push({...r.sourceUpdates[0]}),
    r=>r.sourceUpdates[0].path='../outside',
    r=>r.sourceUpdates[0].sha256='f'.repeat(64),
    r=>r.status='pending']){
    const bad=structuredClone(rule);mutate(bad);assert.throws(()=>validateRecipeBinding(bad,expected));
  }
});
test('independent Node derivation preserves scientific values and original parent',()=>{
  const {rule,expected,original}=fixture(),before=structuredClone(original);
  validateRecipeBinding(rule,expected);
  const derived=expectedMacRecipe(original,rule);
  assert.deepEqual(original,before);
  assert.deepEqual(derived.models,before.models);assert.deepEqual(derived.ortThreads,before.ortThreads);
  assert.equal(derived.sampleFps,8.333333);
  assert.equal(derived.inputSha256['../runtime/pipeline/support.py'],'4'.repeat(64));
  const foreign=structuredClone(rule);foreign.sourceUpdates[0].key='../runtime/unlisted.py';
  assert.throws(()=>expectedMacRecipe(original,foreign),/outside original source maps/);
});
