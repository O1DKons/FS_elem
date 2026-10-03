#!/usr/bin/env node
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {readFileSync, writeFileSync, existsSync} from 'node:fs';
import {join, dirname} from 'node:path';
import {createHash} from 'node:crypto';

const args = process.argv.slice(2);
const scienceArg = args.indexOf('--science-python');
const python = scienceArg < 0 ? 'python3.12' : args[scienceArg + 1];
if (!python) {
  console.error('--science-python requires an executable path');
  process.exit(1);
}
const script = fileURLToPath(new URL('./setup-release.py', import.meta.url));
const result = spawnSync(python, [script, ...args], {stdio: 'inherit'});
if (result.error) console.error(`Cannot run ${python}: ${result.error.message}. See docs/release/installation.md.`);
if (result.error || result.status !== 0) process.exit(result.status ?? 1);
if (!args.includes('--install') && !args.includes('--check')) process.exit(0);
if (Number(process.versions.node.split('.')[0]) !== 24) {
  console.error('Release v1 requires Node.js 24.');process.exit(1);
}
const root = fileURLToPath(new URL('../', import.meta.url));
const lock = join(root, 'apps/web/pnpm-lock.yaml');
const receipt = join(root, '.runtime/frontend-install.json');
const digest = () => createHash('sha256').update(readFileSync(lock)).digest('hex');
const env = {...process.env, PATH: dirname(process.execPath) + ':' + process.env.PATH,
  npm_config_cache: join(root, '.runtime/npm-cache')};
if (args.includes('--install')) {
  const npm = process.platform === 'win32' ? 'npx.cmd' : 'npx';
  const installed = spawnSync(npm, ['--yes', 'pnpm@11.19.0', '--dir', 'apps/web', 'install', '--frozen-lockfile',
    '--store-dir', join(root, '.runtime/pnpm-store')],
    {cwd: root, stdio: 'inherit', env});
  if (installed.error || installed.status !== 0) {
    console.error(installed.error?.message ?? 'Frontend installation failed.');process.exit(installed.status ?? 1);
  }
  const built = spawnSync(process.execPath, [join(root, 'scripts/build.mjs')], {cwd: root, stdio: 'inherit', env});
  if (built.error || built.status !== 0) {
    console.error(built.error?.message ?? 'Frontend build failed.');process.exit(built.status ?? 1);
  }
  writeFileSync(receipt, JSON.stringify({lockSha256: digest(), nodeMajor: 24, pnpmVersion: '11.19.0'}) + '\n');
}
try {
  const state = JSON.parse(readFileSync(receipt, 'utf8'));
  if (state.lockSha256 !== digest() || state.nodeMajor !== 24 || state.pnpmVersion !== '11.19.0' ||
      !existsSync(join(root, 'apps/web/node_modules/vinext/dist/cli.js')))
    throw Error('Frontend does not match the release lock; run setup again.');
  console.log('Frontend lock and installed release verified. Run npm run start:release.');
} catch (error) {console.error(error.message);process.exit(1);}
