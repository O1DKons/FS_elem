import { createHash } from 'node:crypto';
import { existsSync, readFileSync, statSync, lstatSync, realpathSync, mkdirSync, writeFileSync } from 'node:fs';
import { resolve, relative, isAbsolute, dirname, join } from 'node:path';
import { createInterface } from 'node:readline';

const sha = file => createHash('sha256').update(readFileSync(file)).digest('hex');
const read = file => {
  if (statSync(file).size > 16 * 1024 * 1024) throw Error('Bundle metadata is too large');
  return JSON.parse(readFileSync(file, 'utf8'));
};
function inside(root, file) {
  const part = relative(resolve(root), resolve(file));
  return part !== '' && !part.startsWith('..') && !isAbsolute(part);
}
function relativeName(value) {
  if (typeof value !== 'string' || !value || /[\\:]/.test(value) || value.split('/').includes('..') || isAbsolute(value))
    throw Error('Invalid relative bundle path');
}
function installedFile(root, value, canonicalRoot = realpathSync(root)) {
  relativeName(value);
  const file = resolve(root, value);
  if (!inside(root, file) || !inside(canonicalRoot, realpathSync(file)) || lstatSync(file).isSymbolicLink())
    throw Error('Bundle file escapes installed application');
  return file;
}
const ordered = value => Array.isArray(value) ? value.map(ordered) : value && typeof value === 'object'
  ? Object.fromEntries(Object.keys(value).sort().map(key => [key, ordered(value[key])])) : value;
// Python select_profile uses ensure_ascii=True, sorted keys and compact separators.
const canonical = value => JSON.stringify(ordered(value)).replace(/[\u007f-\uffff]/g, c => `\\u${c.charCodeAt(0).toString(16).padStart(4, '0')}`);

export function requireDesktopReady(root) {
  try {
    // Retain the supplied root: each file must still resolve through its live alias.
    const canonicalRoot = realpathSync(root);
    const bundleFile = join(root, 'windows-bundle.json');
    const modelFile = join(root, 'assets/models/manifest-release-v1.json');
    const bundle = read(bundleFile), models = read(modelFile);
    const state = read(join(root, '.runtime/windows-ready.json'));
    const native = models.platforms?.['windows-x64'];
    const nativeSha = createHash('sha256').update(canonical(native)).digest('hex');
    if (bundle.schemaVersion !== 1 || bundle.packageVersion !== '0.2.4' || bundle.platformId !== 'windows-x64' ||
        native?.status !== 'ready' || bundle.nativeProfileSha256 !== nativeSha || state.schemaVersion !== 1 ||
        state.status !== 'complete' || state.bundleSha256 !== sha(bundleFile) ||
        state.modelManifestSha256 !== sha(modelFile) || state.nativeProfileSha256 !== nativeSha)
      throw Error('Desktop bundle/ready binding changed');
    const expected = new Map();
    const windowsPaths = new Set();
    if (!Array.isArray(bundle.files) || !bundle.files.length || bundle.files.length > 100000)
      throw Error('Missing bundle inventory');
    for (const row of bundle.files) {
      relativeName(row.path);
      if (windowsPaths.has(row.path.toLowerCase()) || !Number.isSafeInteger(row.bytes) || row.bytes < 0 || !/^[a-f0-9]{64}$/.test(row.sha256))
        throw Error('Invalid bundle inventory');
      windowsPaths.add(row.path.toLowerCase());
      expected.set(row.path, row.sha256);
    }
    for (const row of models.models) {
      relativeName(row.path);
      if (windowsPaths.has(row.path.toLowerCase()) && !expected.has(row.path)) throw Error('Duplicate Windows model path');
      windowsPaths.add(row.path.toLowerCase());
      if (expected.has(row.path) && expected.get(row.path) !== row.sha256) throw Error('Model/bundle checksum mismatch');
      expected.set(row.path, row.sha256);
    }
    expected.set('assets/models/manifest-release-v1.json', sha(modelFile));
    if (!Array.isArray(state.files) || state.files.length !== expected.size ||
        new Set(state.files.map(r => r.path)).size !== expected.size ||
        state.files.some(row => !expected.has(row.path)))
      throw Error('Incomplete ready receipt');
    // Both exact name coverage and authoritative digest binding precede the physical scan.
    for (const row of state.files) {
      const digest = expected.get(row.path);
      if (!expected.has(row.path) || typeof digest !== 'string' || !/^[a-f0-9]{64}$/.test(digest) || row.sha256 !== digest)
        throw Error('Changed ready checksum binding');
    }
    for (const row of state.files) {
      const info = statSync(installedFile(root, row.path, canonicalRoot), { bigint: true });
      // Windows CPython st_ctime is creation time; Node exposes it as birthtime.
      const ctime = process.platform === 'win32' ? info.birthtimeNs : info.ctimeNs;
      if (!info.isFile() || row.sizeBytes !== Number(info.size) || row.ctimeNs !== ctime.toString() ||
          ['dev', 'ino', 'mtimeNs'].some(key => row[key] !== info[key].toString())) {
        const current = { sizeBytes: Number(info.size), dev: info.dev.toString(), ino: info.ino.toString(),
          mtimeNs: info.mtimeNs.toString(), ctimeNs: ctime.toString() };
        const fields = Object.keys(current).filter(key => row[key] !== current[key]);
        const bounded = values => Object.fromEntries(fields.map(key => [key, String(values[key]).slice(0, 80)]));
        const diagnostic = { isFile: info.isFile(), fields, expected: bounded(row), actual: bounded(current) };
        throw Error('Ready file changed: ' + row.path + '; fingerprintMismatch=' + JSON.stringify(diagnostic));
      }
    }
    return state;
  } catch (error) {
    throw Error('FS_elem first-run readiness is missing or changed. Перезапустите FS_elem для проверки. ' + error.message);
  }
}

export function prepareDesktopConfig(root, requested, environment = process.env) {
  if (!requested && !environment.LOCALAPPDATA) throw Error('Desktop user directory is missing');
  const file = resolve(requested ?? join(environment.LOCALAPPDATA, 'FS_elem/release-web.json'));
  if (inside(root, file) || file === resolve(root)) throw Error('Desktop config must be outside application, in user data');
  const directory = dirname(file);
  const existing = existsSync(file) ? read(file) : {};
  const dataDir = resolve(directory, existing.dataDir ?? 'data');
  const jobsDir = resolve(directory, existing.jobsDir ?? 'jobs');
  if (inside(root, dataDir) || inside(root, jobsDir) || dataDir === resolve(root) || jobsDir === resolve(root))
    throw Error('Jobs/data must stay outside installed application');
  const config = { ...existing, host: '127.0.0.1', port: existing.port ?? 5174, analysisPort: existing.analysisPort ?? 5175,
    python: join(root, '.runtime/venv-science/Scripts/python.exe'), dataDir, jobsDir };
  mkdirSync(directory, { recursive: true });
  mkdirSync(jobsDir, { recursive: true });
  writeFileSync(file, JSON.stringify(config, null, 2) + '\n', 'utf8');
  return file;
}

export function attachDesktopControl(input, shutdown) {
  const lines = createInterface({ input });
  let requested = false;
  const stop = () => { if (!requested) { requested = true; shutdown(); } };
  lines.on('line', line => {
    try { if (JSON.parse(line)?.type === 'shutdown') stop(); } catch { /* Non-control text cannot issue commands. */ }
  });
  lines.on('close', stop); // The owning desktop launcher disappeared.
  return lines;
}
