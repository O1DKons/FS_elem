import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {requireDesktopReady} from '../../scripts/windows-bundle.mjs';

const hash = b => createHash('sha256').update(b).digest('hex');
function fixture({version='0.2.5', included=true, offline=true}={}) {
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'FS_elem offline '));
  const put=(name,body)=>{const file=path.join(root,name);fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file,body);return file;};
  const model={id:'test-model',path:'assets/models/model.bin',sizeBytes:5,sha256:hash('model'),url:'https://example.invalid/model'};
  put(model.path,'model');
  const native={status:'ready'};
  put('assets/models/manifest-release-v1.json',JSON.stringify({models:[model],platforms:{'windows-x64':native}}));
  const files=['assets/models/manifest-release-v1.json',...(included?[model.path]:[])].map(name=>{const body=fs.readFileSync(path.join(root,name));return {path:name,bytes:body.length,sha256:hash(body)};});
  const bundle={schemaVersion:1,packageVersion:version,offline,platformId:'windows-x64',nativeProfileSha256:hash(JSON.stringify(native)),files};
  put('windows-bundle.json',JSON.stringify(bundle));
  const receipt={schemaVersion:1,status:'complete',packageVersion:version,offline:true,bundleSha256:hash(fs.readFileSync(path.join(root,'windows-bundle.json'))),modelManifestSha256:hash(fs.readFileSync(path.join(root,'assets/models/manifest-release-v1.json'))),nativeProfileSha256:bundle.nativeProfileSha256,
    files:[...files,...(!included?[{path:model.path,sha256:model.sha256}]:[])].map(row=>{const s=fs.statSync(path.join(root,row.path),{bigint:true});const ctime=process.platform==='win32'?s.birthtimeNs:s.ctimeNs;return {path:row.path,sha256:row.sha256,sizeBytes:Number(s.size),dev:s.dev.toString(),ino:s.ino.toString(),mtimeNs:s.mtimeNs.toString(),ctimeNs:ctime.toString()};})};
  put('.runtime/windows-ready.json',JSON.stringify(receipt));
  return {root,bundle,receipt,put};
}
const clean=f=>fs.rmSync(f.root,{recursive:true,force:true});

test('model omitted from installer inventory cannot be blessed by a ready receipt',()=>{
  const f=fixture({included:false});
  try {assert.throws(()=>requireDesktopReady(f.root),/model|inventory|состав/i);}finally{clean(f);}
});
test('new offline025 receipt admits the complete local inventory',()=>{
  const f=fixture({version:'0.2.5'});
  try {assert.doesNotThrow(()=>requireDesktopReady(f.root));}finally{clean(f);}
});
test('model size in installer inventory must agree with authoritative manifest',()=>{
  const f=fixture();
  try {
    f.bundle.files.find(r=>r.path==='assets/models/model.bin').bytes=6;
    f.put('windows-bundle.json',JSON.stringify(f.bundle));
    f.receipt.bundleSha256=hash(fs.readFileSync(path.join(f.root,'windows-bundle.json')));
    f.put('.runtime/windows-ready.json',JSON.stringify(f.receipt));
    assert.throws(()=>requireDesktopReady(f.root),/model|size|inventory/i);
  }finally{clean(f);}
});
test('receipt without offline lineage cannot reuse current fingerprints',()=>{
  const f=fixture();
  try {delete f.receipt.offline;f.put('.runtime/windows-ready.json',JSON.stringify(f.receipt));assert.throws(()=>requireDesktopReady(f.root),/binding|offline/i);}finally{clean(f);}
});
