#!/usr/bin/env node
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {readFileSync, writeFileSync, existsSync} from 'node:fs';
import {join, dirname} from 'node:path';
import {profile, prependNodePath} from './release-platform.mjs';
import {createHash} from 'node:crypto';

if (Number(process.versions.node.split('.')[0]) !== 24) {console.error('Release requires Node.js 24.');process.exit(1);}
try {profile();} catch(error) {console.error(error.message);process.exit(1);}
const args = process.argv.slice(2);
if (process.platform === 'win32' && args.includes('--install') && (!args.includes('--science-python') || !args.includes('--pose-python'))) {
  console.error('Windows setup requires explicit --science-python and --pose-python executable paths. See docs/release/installation-windows.md.');process.exit(1);
}
const scienceArg = args.indexOf('--science-python');
const python = scienceArg < 0 ? 'python3.12' : args[scienceArg + 1];
if (!python) {
  console.error('--science-python requires an executable path');
  process.exit(1);
}
const script = fileURLToPath(new URL('./setup-release.py', import.meta.url));
const result = spawnSync(python, [script, ...args], {stdio: 'inherit',
  env: {...prependNodePath(process.env), PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1'}});
if (result.error) console.error(`Cannot run ${python}: ${result.error.message}. See docs/release/installation.md.`);
if (result.error || result.status !== 0) process.exit(result.status ?? 1);
if (!args.includes('--install') && !args.includes('--check')) process.exit(0);
const root = fileURLToPath(new URL('../', import.meta.url));
const lock = join(root, 'apps/web/pnpm-lock.yaml');
const receipt = join(root, '.runtime/frontend-install.json');
const digest = () => createHash('sha256').update(readFileSync(lock)).digest('hex');
const env = {...prependNodePath(process.env), PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1',
  npm_config_cache: join(root, '.runtime/npm-cache')};
if (args.includes('--install')) {
  const candidates = [process.env.npm_execpath && join(dirname(process.env.npm_execpath), 'npx-cli.js'),
    join(dirname(process.execPath), 'node_modules/npm/bin/npx-cli.js'),
    join(dirname(process.execPath), '../lib/node_modules/npm/bin/npx-cli.js')].filter(Boolean);
  const npx = candidates.find(existsSync);
  if (!npx) {console.error('Bundled npm/npx Node CLI is missing; install the standard Node.js24 distribution.');process.exit(1);}
  let installed;
  if (process.platform === 'win32') {
    // Avoid npx's generated .cmd shim in a project path containing '&'.
    const npm = join(dirname(npx), 'npm-cli.js');
    if (!existsSync(npm)) {console.error('Bundled npm Node CLI is missing.');process.exit(1);}
    const bootstrap = join(root, '.runtime/frontend-bootstrap');
    const prepared = spawnSync(process.execPath, [npm, 'install', '--prefix', bootstrap,
      '--no-save', '--package-lock=false', '--ignore-scripts', '--bin-links=false',
      '--no-audit', '--no-fund', 'pnpm@11.19.0'],
      {cwd: root, stdio: 'inherit', env, shell: false});
    if (prepared.error || prepared.status !== 0) {
      console.error(prepared.error?.message ?? 'Pinned pnpm bootstrap failed.');process.exit(prepared.status ?? 1);
    }
    const packageRoot = join(bootstrap, 'node_modules/pnpm');
    let pnpm;
    try {
      const metadata = JSON.parse(readFileSync(join(packageRoot, 'package.json'), 'utf8'));
      const entry = typeof metadata.bin === 'string' ? metadata.bin : metadata.bin?.pnpm;
      if (metadata.version !== '11.19.0' || typeof entry !== 'string' || !existsSync(join(packageRoot, entry)))
        throw Error('Pinned pnpm package or Node entry point is missing.');
      pnpm = join(packageRoot, entry);
    } catch (error) {console.error(error.message);process.exit(1);}
    installed = spawnSync(process.execPath, [pnpm, '--dir', 'apps/web', 'install', '--frozen-lockfile',
      '--store-dir', join(root, '.runtime/pnpm-store')],
      {cwd: root, stdio: 'inherit', env, shell: false});
  } else {
    installed = spawnSync(process.execPath, [npx, '--yes', 'pnpm@11.19.0', '--dir', 'apps/web', 'install', '--frozen-lockfile',
      '--store-dir', join(root, '.runtime/pnpm-store')],
      {cwd: root, stdio: 'inherit', env});
  }
  if (installed.error || installed.status !== 0) {
    console.error(installed.error?.message ?? 'Frontend installation failed.');process.exit(installed.status ?? 1);
  }
  // Use the accepted compiled UI; developer builds remain npm run build.
  writeFileSync(receipt, JSON.stringify({lockSha256: digest(), nodeMajor: 24, pnpmVersion: '11.19.0'}) + '\n');
}
try {
  const state = JSON.parse(readFileSync(receipt, 'utf8'));
  if (state.lockSha256 !== digest() || state.nodeMajor !== 24 || state.pnpmVersion !== '11.19.0' ||
      !existsSync(join(root, 'apps/web/node_modules/vinext/dist/cli.js')) ||
      !existsSync(join(root, 'apps/web/dist/server/index.js')) || !existsSync(join(root, 'apps/web/dist/client')))
    throw Error('Frontend does not match the release lock; run setup again.');
  console.log('Frontend lock and installed release verified. Run npm run start:release.');
} catch (error) {console.error(error.message);process.exit(1);}
