import {test} from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {createServer} from 'node:net';
import {writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {fixture} from './fixtures.mjs';
import {importLegacy} from '../server/importer.mjs';
const script=fileURLToPath(new URL('../scripts/start.mjs',import.meta.url));
async function freePort(){const s=createServer();s.listen(0,'127.0.0.1');await once(s,'listening');const port=s.address().port;await new Promise(r=>s.close(r));return port;}
function start(config,t){const child=spawn(process.execPath,[script,'--config',config],{cwd:'/',stdio:['ignore','pipe','pipe']});let output='';child.stdout.on('data',s=>output+=s);child.stderr.on('data',s=>output+=s);t.after(()=>child.kill());return {child,output:()=>output};}
async function untilReady(port,run){const deadline=Date.now()+20000;while(Date.now()<deadline){if(run.child.exitCode!==null)throw Error(run.output());try{const r=await fetch(`http://127.0.0.1:${port}/api/health`);if(r.ok)return;}catch{}await new Promise(r=>setTimeout(r,100));}throw Error('Readiness timeout: '+run.output());}
test('one launcher works outside repo cwd and stops both services', {timeout:30000},async t=>{
 const f=fixture(t);await importLegacy(f.source,f.dest);const port=await freePort(),analysisPort=await freePort();
 const config=join(f.root,'config.json');writeFileSync(config,JSON.stringify({dataDir:f.dest,port,analysisPort}));
 const run=start(config,t);await untilReady(port,run);
 const page=await fetch(`http://127.0.0.1:${port}/`);assert.equal(page.status,200);assert.match(await page.text(),/Разметка прыжков/);
 const response=await fetch(`http://127.0.0.1:${port}/api/analysis/health`);assert.equal((await response.json()).inferenceAvailable,false);
 const exit=once(run.child,'exit');run.child.kill('SIGTERM');const [code]=await exit;assert.equal(code,0,run.output());
 await assert.rejects(fetch(`http://127.0.0.1:${analysisPort}/health`));
});
test('occupied web port fails without leaving the analysis service or killing its owner',{timeout:30000},async t=>{
 const f=fixture(t);await importLegacy(f.source,f.dest);const owner=createServer();owner.listen(0,'127.0.0.1');await once(owner,'listening');t.after(()=>owner.close());
 const analysisPort=await freePort(),port=owner.address().port;const config=join(f.root,'config.json');writeFileSync(config,JSON.stringify({dataDir:f.dest,port,analysisPort}));
 const run=start(config,t);const [code]=await once(run.child,'exit');assert.notEqual(code,0);assert.equal(owner.listening,true);await assert.rejects(fetch(`http://127.0.0.1:${analysisPort}/health`));
});
