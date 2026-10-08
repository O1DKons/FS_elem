import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { stopOwnedChild } from '../../scripts/release-control.mjs';

// Break: closing API without its private shutdown line bypasses orderly cleanup.
test('controller sends private JSON shutdown and waits for child cleanup', async () => {
  const script = `process.stdin.setEncoding('utf8');let data='';process.stdin.on('data',chunk=>data+=chunk);process.stdin.on('end',()=>{const m=JSON.parse(data);process.exit(m.type==='shutdown'?0:41)});console.log('ready');`;
  const child = spawn(process.execPath, ['-e', script], { stdio: ['pipe', 'pipe', 'pipe'] });
  try {
    await once(child.stdout, 'data');
    assert.equal(await stopOwnedChild(child, true, 1000, 1000), true);
    assert.equal(child.exitCode, 0);
  } finally {
    if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
  }
});

// Break: an unresponsive child blocks stop indefinitely or controller kills unrelated Node.
test('bounded fallback stops only owned child and leaves unrelated sentinel alive', async () => {
  const stuck = spawn(process.execPath, ['-e', "process.stdin.resume();setInterval(()=>{},1000);console.log('ready');"], { stdio: ['pipe', 'pipe', 'pipe'] });
  const sentinel = spawn(process.execPath, ['-e', "setInterval(()=>{},1000);console.log('ready');"], { stdio: ['ignore', 'pipe', 'pipe'] });
  try {
    await Promise.all([once(stuck.stdout, 'data'), once(sentinel.stdout, 'data')]);
    assert.equal(await stopOwnedChild(stuck, true, 50, 1000), true);
    assert.equal(sentinel.exitCode, null);
    assert.equal(sentinel.signalCode, null);
  } finally {
    for (const child of [stuck, sentinel]) {
      if (child.exitCode === null && child.signalCode === null) {
        const ended = once(child, 'exit');
        child.kill('SIGKILL');
        await ended;
      }
    }
  }
});
