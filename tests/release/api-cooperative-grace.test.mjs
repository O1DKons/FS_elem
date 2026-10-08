import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { API_GRACE_MS, stopOwnedChild } from '../../scripts/release-control.mjs';

// Break: the old 12s budget force-kills a correctly cleaning API before completion.
// Controlled child cleans for 21s, covering a 19s cleanup plus overhead.
// This exercises the controller budget, not actual Main native cleanup.
test('slow cooperative API completes with cleanup overhead beyond 20s', { timeout: 29000 }, async () => {
  const child = spawn(process.execPath, ['-e', `process.stdin.setEncoding('utf8');let input='';process.stdin.on('data',s=>input+=s);process.stdin.on('end',()=>{if(JSON.parse(input).type!=='shutdown')process.exit(42);setTimeout(()=>{console.log('cleanup-complete');process.exit(0)},21000)});console.log('ready');`], { stdio: ['pipe', 'pipe', 'pipe'] });
  let output = '';
  child.stdout.setEncoding('utf8').on('data', data => output += data);
  try {
    await once(child.stdout, 'data');
    assert.equal(await stopOwnedChild(child, 'stdin', API_GRACE_MS), true);
    assert.equal(child.exitCode, 0);
    assert.equal(child.signalCode, null);
    assert.match(output, /cleanup-complete/);
  } finally {
    if (child.exitCode === null && child.signalCode === null) {
      const ended = once(child, 'close');
      child.kill('SIGKILL');
      await ended;
    }
  }
});
