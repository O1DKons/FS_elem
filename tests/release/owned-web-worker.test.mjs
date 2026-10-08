import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { UI_GRACE_MS, stopOwnedChild } from '../../scripts/release-control.mjs';

function ready(child) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { clean(); reject(Error('guarded entry did not start')); }, 2500);
    const message = value => { clean(); resolve(value); };
    const failed = () => { clean(); reject(Error('guarded entry exited before ready')); };
    function clean() {
      clearTimeout(timer);child.off('message', message);child.off('close', failed);child.off('error', failed);
    }
    child.once('message', message);child.once('close', failed);child.once('error', failed);
  });
}

// Runs the actual production entry and wrapper in an isolated dependency fixture.
// Store ownership has a real file descriptor and file: cleanup must unlink it.
// The SDK server boundary is controlled; compiled UI, SQLite and sockets are not tested.
function prepare(root, config) {
  const scripts = path.join(root, 'scripts');
  const server = path.join(root, 'server');
  const sdk = path.join(root, 'apps/web/node_modules/vinext/dist/server');
  for (const dir of [scripts, server, sdk]) fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(root, 'package.json'), '{"type":"module"}\n');
  for (const entry of ['release-web-worker.mjs', 'release-owned-web-worker.mjs']) {
    fs.copyFileSync(fileURLToPath(new URL(`../../scripts/${entry}`, import.meta.url)), path.join(scripts, entry));
  }
  const data = path.join(root, 'owned-data');
  fs.writeFileSync(path.join(scripts, 'config.mjs'), `export const projectRoot=${JSON.stringify(root)};export function loadConfig(_root,file){if(file!==${JSON.stringify(config)})throw Error('wrong-config-argv');return {host:'127.0.0.1',port:5174,dataDir:${JSON.stringify(data)}}}\n`);
  fs.writeFileSync(path.join(server, 'store.mjs'), `import fs from 'node:fs';import path from 'node:path';export function openStore(dir){fs.mkdirSync(dir,{recursive:true});const file=path.join(dir,'store.fixture');const fd=fs.openSync(file,'wx');return {close(){fs.closeSync(fd);fs.unlinkSync(file)}}}\n`);
  fs.writeFileSync(path.join(server, 'api.mjs'), `export function createApi(){return (_req,_res,next)=>next()}\n`);
  fs.writeFileSync(path.join(sdk, 'prod-server.js'), `import {EventEmitter} from 'node:events';export async function startProdServer(config){const server=new EventEmitter();server.on('request',()=>{});server.close=callback=>setTimeout(callback,20);server.closeAllConnections=()=>{};return {server,port:config.port}}\n`);
  return path.join(data, 'store.fixture');
}

for (const mode of ['wrapper-shutdown', 'wrapper-disconnect', 'direct-disconnect']) {
  // Breaks: missing real main export, import-only dispatch, duplicate startup,
  // wrong config argv, missing ready, or bypassing real entry's store cleanup.
  test(`actual guarded entry starts and cleans on ${mode}`, { timeout: 12000 }, async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'fs-elem-guarded-entry-'));
    let child;
    try {
      const config = path.join(root, 'Каталог & конфиг.json');
      const ownedFile = prepare(root, config);
      const entry = mode === 'direct-disconnect' ? 'release-web-worker.mjs' : 'release-owned-web-worker.mjs';
      child = spawn(process.execPath, [path.join(root, 'scripts', entry), config], { stdio: ['ignore', 'pipe', 'pipe', 'ipc'] });
      assert.deepEqual(await ready(child), { ready: true, port: 5174, mode: 'production' });
      assert.equal(fs.existsSync(ownedFile), true);
      if (mode === 'wrapper-shutdown') assert.equal(await stopOwnedChild(child, 'ipc', UI_GRACE_MS), true);
      else {
        const exited = new Promise((resolve, reject) => {
          if (child.exitCode !== null || child.signalCode !== null) { resolve(); return; }
          const completed = () => { clean(); resolve(); };
          const failed = error => { clean(); reject(error); };
          const timer = setTimeout(() => { clean(); reject(Error('guarded worker failed to exit')); }, UI_GRACE_MS + 1000);
          function clean() {
            clearTimeout(timer); child.off('exit', completed); child.off('error', failed);
          }
          child.once('exit', completed); child.once('error', failed);
        });
        if (child.connected) child.disconnect();
        await exited;
      }
      assert.equal(child.exitCode, 0);
      assert.equal(child.signalCode, null);
      assert.equal(fs.existsSync(ownedFile), false);
    } finally {
      if (child?.exitCode === null && child.signalCode === null) await stopOwnedChild(child, false, 1000, 1000);
      fs.rmSync(root, { recursive: true, force: true });
    }
  });
}
