#!/usr/bin/env node
import { readFileSync, readdirSync, existsSync, lstatSync, realpathSync } from 'node:fs';
import { resolve, join, relative, sep, posix } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';

const media = new Set([
  'grant-demo/media/example-1a.mp4', 'grant-demo/media/example-2a.mp4',
  'grant-demo/screenshots/main-desktop.png', 'grant-demo/screenshots/mobile-390.png',
  'grant-demo/screenshots/timeline-2a.png'
]);
const models = new Set(['assets/models/flight.joblib', 'assets/models/family.joblib', 'assets/models/nominal.joblib']);
// Installed upstream checkpoints are runtime inputs; archive only manifest rows.
// The row admission below still rejects listing any ONNX in the public payload.
const ignored = p => ['assets/models/yolox.onnx', 'assets/models/rtmw.onnx'].includes(p) ||
  p.split('/').some(v => ['.git', 'node_modules', '__pycache__'].includes(v)) ||
  p.startsWith('.runtime/') || p.startsWith('dist/') || p.startsWith('phase-cache/') ||
  p.startsWith('apps/web/.vinext/') || p.startsWith('apps/web/dist/') ||
  p.startsWith('apps/web/.next/') || /(?:\.pyc|\.tsbuildinfo)$/.test(p);

export function verifyPayload(root, { requireReady = false } = {}) {
  root = realpathSync(root instanceof URL ? fileURLToPath(root) : resolve(root));
  const manifest = JSON.parse(readFileSync(join(root, 'source-manifest.json'), 'utf8'));
  if (requireReady && (manifest.readyForRelease !== true ||
      !/^[a-f0-9]{64}$/.test(manifest.checks?.commonAcceptanceSha256 ?? '')))
    throw Error('Release not ready: common integration acceptance is required');
  if (!Array.isArray(manifest.files)) throw Error('Manifest files are missing');
  const expected = new Set(['source-manifest.json']);
  let bytes = 0;
  for (const row of manifest.files) {
    const p = row.path;
    if (typeof p !== 'string' || p.startsWith('/') || p.includes('\\') ||
        posix.normalize(p) !== p || p.split('/').some(v => !v || v === '..' || v === '.'))
      throw Error(`unsafe path: ${p}`);
    if (expected.has(p)) throw Error(`duplicate path: ${p}`);
    expected.add(p);
    if (p.split('/').some(v => ['.git', '.runtime', 'node_modules', 'work', 'data', 'phase-cache', '__pycache__'].includes(v)))
      throw Error(`private path: ${p}`);
    if (/\.(?:mp4|mov|mkv|webm|png|jpe?g|gif|webp)$/i.test(p) && !media.has(p))
      throw Error(`unapproved media: ${p}`);
    if (/\.(?:onnx|pt|pth|pkl|pickle|joblib)$/i.test(p) && !models.has(p))
      throw Error(`unapproved model: ${p}`);
    const file = join(root, p);
    if (!existsSync(file)) throw Error(`missing file: ${p}`);
    if (!lstatSync(file).isFile() || realpathSync(file) !== file)
      throw Error(`symlink or non-file: ${p}`);
    const body = readFileSync(file);
    if (body.length !== row.bytes || createHash('sha256').update(body).digest('hex') !== row.sha256)
      throw Error(`payload mismatch: ${p}`);
    bytes += body.length;
  }
  function walk(dir) {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const file = join(dir, entry.name), p = relative(root, file).split(sep).join('/');
      if (ignored(p + (entry.isDirectory() ? '/' : ''))) continue;
      if (entry.isDirectory()) walk(file);
      else if (!expected.has(p)) throw Error(`unlisted file: ${p}`);
    }
  }
  walk(root);
  return { files: manifest.files.length, bytes, readyForRelease: manifest.readyForRelease === true };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { console.log(JSON.stringify(verifyPayload(process.argv[2] || '.', {
    requireReady: process.argv.includes('--require-ready')
  }))); } catch (error) { console.error(error.message); process.exitCode = 1; }
}
