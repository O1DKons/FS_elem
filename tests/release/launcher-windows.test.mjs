import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

// Break: cd omits /d, delayed expansion corrupts arguments, or launcher swallows exit status.
// Requires native cmd.exe; this does not test the real backend or imply a Windows release PASS.
test('cmd launcher preserves quoted path arguments and child exit status', { skip: process.platform !== 'win32' }, () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'FS_elem & Кириллица '));
  const app = path.join(root, 'app');
  try {
    fs.mkdirSync(path.join(app, 'scripts'), { recursive: true });
    fs.copyFileSync(fileURLToPath(new URL('../../FS_elem.cmd', import.meta.url)), path.join(app, 'FS_elem.cmd'));
    fs.writeFileSync(path.join(app, 'scripts', 'start-release.mjs'), 'console.log(JSON.stringify({cwd:process.cwd(),argv:process.argv.slice(2)}));process.exit(37);\n');
    const env = { ...process.env };
    for (const key of Object.keys(env)) if (key.toLowerCase() === 'path') delete env[key];
    env.Path = `${path.dirname(process.execPath)};${process.env.SystemRoot}\\System32`;
    const result = spawnSync(process.env.ComSpec || 'cmd.exe', ['/d', '/v:off', '/s', '/c', `""${app}\\FS_elem.cmd" --input "D:\\Видео & пробелы\\test!.mp4" --api-port 5295"`], { env, encoding: 'utf8', timeout: 10000 });
    assert.equal(result.error, undefined);
    assert.equal(result.status, 37, result.stderr);
    const output = result.stdout.split(/\r?\n/).find(line => line.startsWith('{'));
    assert.deepEqual(JSON.parse(output), { cwd: app, argv: ['--open', '--input', 'D:\\Видео & пробелы\\test!.mp4', '--api-port', '5295'] });
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});
