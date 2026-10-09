import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { PassThrough } from 'node:stream';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { once } from 'node:events';
import { fileURLToPath } from 'node:url';

let desktop;
try { desktop = await import('../../scripts/windows-bundle.mjs'); } catch (error) {
  if (error.code !== 'ERR_MODULE_NOT_FOUND') throw error;
}

// Break: accepting malformed/missing receipts or consuming unrelated stdin as control.
test('missing desktop readiness receipt is rejected', () => {
  assert.ok(desktop, 'Desktop readiness checker is not implemented');
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'FS_elem desktop '));
  try { assert.throws(() => desktop.requireDesktopReady(root), /first|ready|bundle/i); }
  finally { fs.rmSync(root, { recursive: true, force: true }); }
});

test('desktop config keeps jobs and data outside the application directory', () => {
  assert.ok(desktop, 'Desktop config helper is not implemented');
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'FS_elem & Кириллица '));
  try {
    const app = path.join(root, 'program'); fs.mkdirSync(app);
    const configFile = path.join(root, 'user', 'release-web.json');
    const result = desktop.prepareDesktopConfig(app, configFile);
    const config = JSON.parse(fs.readFileSync(configFile, 'utf8'));
    assert.equal(result, configFile);
    assert.equal(config.dataDir, path.join(root, 'user', 'data'));
    assert.equal(config.jobsDir, path.join(root, 'user', 'jobs'));
    assert.equal(config.python, path.join(app, '.runtime/venv-science/Scripts/python.exe'));
    assert.throws(() => desktop.prepareDesktopConfig(app, path.join(app, 'config.json')), /user|outside/i);
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});

test('shutdown command and parent EOF each invoke one cooperative stop', async () => {
  assert.ok(desktop, 'Desktop control helper is not implemented');
  for (const command of [true, false]) {
    const input = new PassThrough(); let stops = 0;
    const control = desktop.attachDesktopControl(input, () => { stops++; });
    input.write('unrelated log\n{"type":"other"}\n');
    if (command) input.write('{"type":"shutdown"}\n');
    input.end();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(stops, 1);
    control.close();
  }
});

const hash = body => createHash('sha256').update(body).digest('hex');
function syntheticDesktop(root) {
  const app = path.join(root, 'program');
  const put = (name, body) => {
    const p = path.join(app, name); fs.mkdirSync(path.dirname(p), { recursive: true }); fs.writeFileSync(p, body); return p;
  };
  for (const name of ['start-release.mjs', 'config.mjs', 'release-control.mjs', 'windows-bundle.mjs'])
    put('scripts/' + name, fs.readFileSync(fileURLToPath(new URL('../../scripts/' + name, import.meta.url))));
  // Controlled dependencies exercise the real launcher; no native Windows or inference claim.
  put('scripts/release-platform.mjs', `export const profile=()=>({id:'windows-x64',pythonParts:['Scripts','python.exe']});export const releaseRecipeName=()=> 'test.json';export const requireWindowsRecipe=()=>{};export const browserCommand=()=>[];export const resolveExecutable=(p,root)=>p;`);
  put('scripts/release-owned-web-worker.mjs', `const held=setInterval(()=>{},1000);process.on('message',m=>{if(m?.type==='shutdown'){clearInterval(held);process.exit(0);}});process.send({ready:true});`);
  const python = put('.runtime/venv-science/Scripts/python.exe', '#!/bin/sh\nexec /usr/bin/python3 "$@"\n');
  fs.chmodSync(python, 0o755);
  put('configs/test.json', '{}');
  put('apps/web/dist/server/index.js', '// synthetic compiled UI');
  put('apps/web/dist/client/index.html', 'fixture');
  put('services/analysis/server.py', `import json,sys,os\nfrom pathlib import Path\nPath('test-api-argv.json').write_text(json.dumps(sys.argv))\nprint('diagnostic before ready',flush=True)\nprint(json.dumps({'port':int(sys.argv[sys.argv.index('--port')+1])}),flush=True)\nfor line in sys.stdin:\n if json.loads(line).get('type')=='shutdown':break\n`);
  const native = {status: 'ready'};
  const manifest = put('assets/models/manifest-release-v1.json', JSON.stringify({schemaVersion: 1, models: [], platforms: {'windows-x64': native}}));
  const nativeSha = hash(JSON.stringify(native));
  const files = ['.runtime/venv-science/Scripts/python.exe', 'services/analysis/server.py', 'assets/models/manifest-release-v1.json'];
  const inventory = files.map(name => { const body = fs.readFileSync(path.join(app, name)); return { path: name, bytes: body.length, sha256: hash(body) }; });
  const bundle = put('windows-bundle.json', JSON.stringify({schemaVersion: 1, packageVersion: '0.2.4', platformId: 'windows-x64', nativeProfileSha256: nativeSha, files: inventory}));
  put('.runtime/windows-ready.json', JSON.stringify({schemaVersion: 1, status: 'complete', bundleSha256: hash(fs.readFileSync(bundle)), nativeProfileSha256: nativeSha, modelManifestSha256: hash(fs.readFileSync(manifest)), files: inventory.map(row => {
    const s = fs.statSync(path.join(app, row.path), {bigint: true});
    return {path: row.path, sha256: row.sha256, sizeBytes: Number(s.size), dev:s.dev.toString(),ino:s.ino.toString(),mtimeNs:s.mtimeNs.toString(),ctimeNs:s.ctimeNs.toString()};
  })}));
  return app;
}

test('desktop launcher reports own readiness and stops API/UI on stdin shutdown', {skip:process.platform === 'win32'}, async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'FS_elem & Кириллица '));
  let child;
  try {
    const app = syntheticDesktop(root), config = path.join(root, 'user/release-web.json');
    child = spawn(process.execPath, [path.join(app, 'scripts/start-release.mjs'), '--desktop', '--config', config], {stdio:['pipe','pipe','pipe']});
    let out='', err=''; child.stderr.on('data', b=>{err+=b;});
    const ended = once(child,'close');
    const ready = new Promise((resolve,reject) => {
      const timer=setTimeout(()=>reject(Error('Synthetic desktop readiness timeout: '+err)),5000);
      child.once('exit',()=>{clearTimeout(timer);reject(Error('Desktop exited before ready: '+err));});
      child.stdout.on('data', b=>{
        out+=b;
        for(const line of out.split('\n')) try {
          const value=JSON.parse(line);if(value.type==='ready'){clearTimeout(timer);resolve(value);}
        }catch{}
      });
    });
    assert.equal((await ready).url,'http://127.0.0.1:5174/analysis');
    const apiArgs=JSON.parse(fs.readFileSync(path.join(app,'test-api-argv.json')));
    assert.equal(apiArgs[apiArgs.indexOf('--jobs')+1],path.join(root,'user/jobs'));
    child.stdin.end('{"type":"shutdown"}\n');
    assert.deepEqual(await ended,[0,null]);
    assert.match(out,/"type":"stopped"/);
  } finally {
    if(child?.exitCode===null) {child.kill();await once(child,'close');}
    fs.rmSync(root,{recursive:true,force:true});
  }
});
