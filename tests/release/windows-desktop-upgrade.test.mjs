import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {prepareDesktopConfig} from '../../scripts/windows-bundle.mjs';

test('retained025 user config switches old app interpreter while preserving results and sentinels',()=>{
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'FS_elem upgrade & Кириллица '));
  try {
    const oldApp=path.join(root,'old-app'),newApp=path.join(root,'new-app'),user=path.join(root,'user');
    const dataDir=path.join(user,'data'),jobsDir=path.join(user,'jobs');
    for(const dir of [oldApp,newApp,dataDir,jobsDir])fs.mkdirSync(dir,{recursive:true});
    const result=path.join(dataDir,'previous-result.json'),sentinel=path.join(jobsDir,'user-sentinel.txt');
    fs.writeFileSync(result,'{"preserve":"prior result"}\n');
    fs.writeFileSync(sentinel,'user-owned data must survive\n');
    const file=path.join(user,'release-web.json');
    const previous={host:'127.0.0.1',port:5174,analysisPort:5175,
      python:path.join(oldApp,'.runtime/venv-science/Scripts/python.exe'),dataDir,jobsDir,userPreference:'preserve'};
    fs.writeFileSync(file,JSON.stringify(previous));
    const before=new Map([[result,fs.readFileSync(result)],[sentinel,fs.readFileSync(sentinel)]]);
    const beforeFiles=[...fs.readdirSync(dataDir),...fs.readdirSync(jobsDir)].sort();

    assert.equal(prepareDesktopConfig(newApp,file),file);
    const current=JSON.parse(fs.readFileSync(file,'utf8'));
    assert.equal(current.python,path.join(newApp,'.runtime/venv-science/Scripts/python.exe'));
    assert.notEqual(current.python,previous.python);
    assert.deepEqual({...current,python:previous.python},previous);
    for(const [name,body] of before)assert.deepEqual(fs.readFileSync(name),body);
    assert.deepEqual([...fs.readdirSync(dataDir),...fs.readdirSync(jobsDir)].sort(),beforeFiles);
    assert.deepEqual(fs.readdirSync(newApp),[],'Config preparation must not modify application payload');
    assert.deepEqual(fs.readdirSync(oldApp),[],'The previous application path remains untouched');
  }finally{fs.rmSync(root,{recursive:true,force:true});}
});
