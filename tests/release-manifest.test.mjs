import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, mkdirSync, rmSync, symlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
import { verifyPayload } from '../scripts/verify-release-payload.mjs';

function fixture(t) {
  const root = mkdtempSync(join(tmpdir(), 'release-manifest-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const body = 'bounded public fixture\n';
  writeFileSync(join(root, 'README.md'), body);
  const manifest = { schemaVersion: 1, readyForRelease: false, files: [{
    path: 'README.md', bytes: Buffer.byteLength(body),
    sha256: createHash('sha256').update(body).digest('hex')
  }] };
  const save = () => writeFileSync(join(root, 'source-manifest.json'), JSON.stringify(manifest));
  save(); return { root, manifest, save };
}

test('pending exact payload verifies but cannot be promoted', t => {
  const f = fixture(t); assert.equal(verifyPayload(f.root).files, 1);
  assert.throws(() => verifyPayload(f.root, { requireReady: true }), /not ready/);
});
test('changed or missing accepted bytes fail', t => {
  const f = fixture(t); writeFileSync(join(f.root, 'README.md'), 'changed');
  assert.throws(() => verifyPayload(f.root), /mismatch/);
  rmSync(join(f.root, 'README.md'));
  assert.throws(() => verifyPayload(f.root), /missing/);
});
test('unlisted private files fail', t => {
  const f = fixture(t); writeFileSync(join(f.root, 'private-source.mov'), 'private');
  assert.throws(() => verifyPayload(f.root), /unlisted/);
});
test('traversal, duplicate paths and symlink entries fail', t => {
  const f = fixture(t); f.manifest.files.push({ ...f.manifest.files[0] }); f.save();
  assert.throws(() => verifyPayload(f.root), /duplicate/);
  f.manifest.files.pop(); f.manifest.files[0].path = '../outside'; f.save();
  assert.throws(() => verifyPayload(f.root), /unsafe/);
  f.manifest.files[0].path = 'README.md'; f.save(); rmSync(join(f.root, 'README.md'));
  symlinkSync('source-manifest.json', join(f.root, 'README.md'));
  assert.throws(() => verifyPayload(f.root), /symlink/);
});
test('listed runtime cache and unapproved athlete media fail', t => {
  const f = fixture(t);
  for (const name of ['.runtime/job.json', 'work/pose.json', 'data/labels.json', 'grant-demo/media/third.mp4']) {
    f.manifest.files[0].path = name; f.save();
    assert.throws(() => verifyPayload(f.root), /private|unapproved/);
  }
});
test('installed dependencies do not become release payload', t => {
  const f = fixture(t); mkdirSync(join(f.root, 'node_modules'));
  writeFileSync(join(f.root, 'node_modules', 'installed.js'), 'dependency');
  assert.equal(verifyPayload(f.root).files, 1);
});
test('installed known checkpoints stay outside payload but other models fail', t => {
  const f = fixture(t); mkdirSync(join(f.root, 'assets', 'models'), { recursive: true });
  writeFileSync(join(f.root, 'assets', 'models', 'yolox.onnx'), 'installed fixture');
  writeFileSync(join(f.root, 'assets', 'models', 'rtmw.onnx'), 'installed fixture');
  assert.equal(verifyPayload(f.root).files, 1);
  writeFileSync(join(f.root, 'assets', 'models', 'experimental.joblib'), 'private fixture');
  assert.throws(() => verifyPayload(f.root), /unlisted/);
});
test('the current candidate has exact declared public payload', () => {
  const root = new URL('../', import.meta.url);
  assert.ok(verifyPayload(root).files > 190);
});
