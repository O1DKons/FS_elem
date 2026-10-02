import {loadConfig} from '../scripts/config.mjs';
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {fileURLToPath} from 'node:url';
test('analysis readiness declares no inference and exits cleanly on termination',async t=>{
 const child=spawn(process.env.FS_TEST_PYTHON || loadConfig().python,[fileURLToPath(new URL('../services/analysis/server.py',import.meta.url)),'--port','0'],{stdio:['ignore','pipe','pipe']});
 t.after(()=>child.kill());
 const ready=await Promise.race([once(child.stdout,'data').then(([s])=>JSON.parse(s.toString())),once(child,'exit').then(()=>{throw Error('Service did not become ready')})]);
 const r=await fetch(`http://127.0.0.1:${ready.port}/health`);const body=await r.json();
 assert.equal(r.status,200);assert.equal(body.service,'fs-elem-analysis');assert.equal(body.inferenceAvailable,false);
 const exit=once(child,'exit');child.kill('SIGTERM');await exit;
});
