import test from 'node:test';
import assert from 'node:assert/strict';
import { profile, prependNodePath, resolveExecutable, browserCommand, releaseRecipeName, requireWindowsRecipe } from '../../scripts/release-platform.mjs';

// Break: selecting a Mac profile on Windows or accepting an unsupported architecture.
test('native profiles reject unsupported OS and architecture', () => {
  assert.equal(profile('win32', 'x64').id, 'windows-x64');
  assert.equal(profile('darwin', 'arm64').id, 'macos-arm64');
  for (const [os, arch] of [['linux', 'x64'], ['win32', 'arm64'], ['darwin', 'x64']]) {
    assert.throws(() => profile(os, arch), /Unsupported/);
  }
});

// Break: Windows launches a Mac recipe or enters inference with pending dependency hashes.
test('Windows selects its native CPU4/1 recipe and rejects pending provenance', () => {
  assert.equal(releaseRecipeName('windows-x64'), 'axel-release-ort4-windows-x64-v2.json');
  assert.equal(releaseRecipeName('macos-arm64', 'ort2'), 'axel-release-ort2-v2.json');
  assert.throws(() => releaseRecipeName('windows-x64', 'ort2'), /CPU4/);
  assert.throws(() => requireWindowsRecipe({ platformProvenance: { id: 'windows-x64', status: 'pending' } }, { status: 'pending-metadata' }), /pending/);
});

// Break: ready metadata alone masks a stale backend hash or Unix interpreter path.
test('native recipe guard binds dependencies, source hashes and native executables', () => {
  const native = { status: 'ready', environments: { science: { lockSha256: 'a'.repeat(64) }, pose: { lockSha256: 'b'.repeat(64) } }, ffmpeg: { sha256: 'c'.repeat(64) } };
  const recipe = { sciencePython: '../.runtime/venv-science/Scripts/python.exe', posePython: '../.runtime/venv-pose/Scripts/python.exe', ffmpeg: { path: '../.runtime/bin/ffmpeg.exe', sha256: 'c'.repeat(64) }, ortThreads: { intraOpNumThreads: 4, interOpNumThreads: 1 }, inputSha256: { '../runtime/pipeline/support.py': 'd'.repeat(64) }, platformProvenance: { id: 'windows-x64', status: 'ready', scienceLockSha256: 'a'.repeat(64), poseLockSha256: 'b'.repeat(64), ffmpegSha256: 'c'.repeat(64), backendRuntimeHashes: { '../runtime/pipeline/support.py': 'd'.repeat(64) } } };
  assert.equal(requireWindowsRecipe(recipe, native), recipe);
  assert.throws(() => requireWindowsRecipe({ ...recipe, sciencePython: '../.runtime/venv-science/bin/python' }, native), /pending/);
  assert.throws(() => requireWindowsRecipe({ ...recipe, inputSha256: {} }, native), /pending/);
  assert.throws(() => requireWindowsRecipe({ ...recipe, ortThreads: { intraOpNumThreads: 2, interOpNumThreads: 1 } }, native), /pending/);
});

// Break: colon PATH concatenation or duplicate Path/PATH makes Node invisible on Windows.
test('Windows receives one case-insensitive PATH with native delimiter', () => {
  const env = prependNodePath({ Path: 'C:\\tools', PATH: 'C:\\other', KEEP: 'yes' }, 'C:\\Program Files\\nodejs\\node.exe', 'win32');
  assert.equal(env.Path, 'C:\\Program Files\\nodejs;C:\\tools');
  assert.equal(env.KEEP, 'yes');
  assert.equal(Object.hasOwn(env, 'PATH'), false);
});

// Break: resolving only slash paths runs a wrong interpreter from PATH.
test('relative Windows executables stay relative to project and bare names use PATH', () => {
  assert.equal(resolveExecutable('.runtime\\venv-science\\Scripts\\python.exe', 'D:\\Каталог & space', 'win32'), 'D:\\Каталог & space\\.runtime\\venv-science\\Scripts\\python.exe');
  assert.equal(resolveExecutable('python', 'D:\\project', 'win32'), 'python');
  assert.equal(resolveExecutable('C:\\Python\\python.exe', 'D:\\project', 'win32'), 'C:\\Python\\python.exe');
});

// Break: opening arbitrary URLs or interpolating localhost URL through a shell.
test('browser command accepts only loopback HTTP and uses argument array', () => {
  assert.deepEqual(browserCommand('http://127.0.0.1:5174/', 'win32'), ['explorer.exe', ['http://127.0.0.1:5174/']]);
  assert.deepEqual(browserCommand('http://127.0.0.1:5174/', 'darwin'), ['/usr/bin/open', ['http://127.0.0.1:5174/']]);
  assert.deepEqual(browserCommand('http://127.0.0.1:5174/analysis', 'win32'), ['explorer.exe', ['http://127.0.0.1:5174/analysis']]);
  for (const url of ['https://example.com/', 'file:///C:/x', 'http://user@127.0.0.1:5174/', 'http://127.0.0.1:5174/?x=1']) {
    assert.throws(() => browserCommand(url, 'win32'), /loopback/);
  }
});
