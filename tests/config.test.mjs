import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {loadConfig} from '../scripts/config.mjs';
test('configuration paths are relative to the project, not shell cwd', t=>{
 const root=mkdtempSync(join(tmpdir(),'fs-config-'));t.after(()=>rmSync(root,{recursive:true,force:true}));
 writeFileSync(join(root,'config.local.json'),JSON.stringify({dataDir:'custom data',port:6100,analysisPort:6101}));
 const c=loadConfig(root);assert.equal(c.dataDir,join(root,'custom data'));assert.equal(c.port,6100);assert.equal(c.host,'127.0.0.1');
});
test('rejects externally exposed host and invalid or shared ports', t=>{
 const root=mkdtempSync(join(tmpdir(),'fs-config-'));t.after(()=>rmSync(root,{recursive:true,force:true}));
 for(const patch of [{host:'0.0.0.0'},{port:0},{port:1.5},{port:70000},{port:5175},{python:''}]){
  writeFileSync(join(root,'config.local.json'),JSON.stringify(patch));assert.throws(()=>loadConfig(root));
 }
});
