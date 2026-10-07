#!/usr/bin/env node
import {spawn, spawnSync} from 'node:child_process';
import {once} from 'node:events';
import {createInterface} from 'node:readline';
import {join} from 'node:path';
import {mkdirSync, writeFileSync, existsSync} from 'node:fs';
import {loadConfig, projectRoot} from './config.mjs';

const children = [];
let stopping = false;
async function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  await Promise.all(children.map(async child => {
    if (!child.pid || child.exitCode !== null || child.signalCode !== null) return;
    const ended = once(child, 'exit');
    child.kill('SIGTERM');
    const timer = setTimeout(() => child.kill('SIGKILL'), 12000);
    await ended;
    clearTimeout(timer);
  }));
  process.exit(code);
}
process.on('SIGINT', () => stop());
process.on('SIGTERM', () => stop());
function ready(child, subscribe, accept) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(Error('Service readiness timed out')), 15000);
    const fail = () => {clearTimeout(timer); reject(Error('Service failed to start'));};
    child.once('error', fail);
    child.once('exit', fail);
    subscribe(value => {
      try {
        if (!accept(value)) return;
        clearTimeout(timer);
        child.off('error', fail);child.off('exit', fail);
        resolve();
      } catch (error) {clearTimeout(timer);reject(error);}
    });
  });
}
function watch(child) {
  child.on('exit', () => {
    if (!stopping) {console.error('Один из сервисов остановился.');stop(1);}
  });
}

try {
  if (Number(process.versions.node.split('.')[0]) !== 24)
    throw Error('FS_elem требует Node.js 24. См. docs/release/installation.md.');
  const args = process.argv.slice(2);
  const options = {};
  let openBrowser = false;
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--open' && !openBrowser) {openBrowser = true; continue;}
    if (!['--config', '--profile', '--max-wall-seconds'].includes(args[i]) || !args[i + 1] || args[i] in options)
      throw Error('Usage: node scripts/start-release.mjs [--open] [--profile ort4|ort2] [--config web-config.json] [--max-wall-seconds 1..5400]');
    options[args[i]] = args[++i];
  }
  const maxWallSeconds = Number(options['--max-wall-seconds'] ?? 5400);
  if (!Number.isInteger(maxWallSeconds) || maxWallSeconds < 1 || maxWallSeconds > 5400)
    throw Error('Analysis deadline must be an integer from 1 to 5400 seconds');
  const profile = options['--profile'] ?? 'ort4';
  if (!['ort4', 'ort2'].includes(profile)) throw Error('Release profile must be ort4 or ort2');
  const recipe = join(projectRoot, `configs/axel-release-${profile}-v2.json`);
  if (!existsSync(recipe)) throw Error('В пакете отсутствует профиль анализа. Распакуйте полный пакет FS_elem.');
  const python = join(projectRoot, '.runtime/venv-science/bin/python');
  if (!existsSync(python))
    throw Error('Первоначальная настройка FS_elem ещё не выполнена. Запустите npm run setup:release с Python 3.12 и 3.9; команды в docs/release/installation.md.');
  if (!existsSync(join(projectRoot, 'apps/web/dist/server/index.js')) ||
      !existsSync(join(projectRoot, 'apps/web/dist/client')))
    throw Error('Готовый интерфейс отсутствует. Выполните первоначальную настройку: docs/release/installation.md.');
  const checked = spawnSync(process.execPath, [join(projectRoot, 'scripts/setup-release.mjs'), '--check',
    '--science-python', python], {stdio: 'inherit'});
  if (checked.error || checked.status !== 0) throw Error('Зависимости FS_elem не прошли проверку. Выполните настройку: docs/release/installation.md.');
  const defaultConfig = join(projectRoot, '.runtime/release-web.json');
  if (!options['--config'] && !existsSync(defaultConfig)) {
    mkdirSync(join(projectRoot, '.runtime'), {recursive: true});
    writeFileSync(defaultConfig, JSON.stringify({host: '127.0.0.1', port: 5174, analysisPort: 5175,
      python: '.runtime/venv-science/bin/python', dataDir: '.runtime/data'}, null, 2) + '\n', {flag: 'wx'});
  }
  const configFile = options['--config'] ?? defaultConfig;
  const config = loadConfig(projectRoot, configFile);
  const analysis = spawn(python, [join(projectRoot, 'services/analysis/server.py'), '--port', String(config.analysisPort),
    '--config', recipe, '--jobs', join(projectRoot, '.runtime/jobs'),
    '--max-wall-seconds', String(maxWallSeconds)],
    {cwd: projectRoot, stdio: ['ignore', 'pipe', 'inherit']});
  children.push(analysis);
  const lines = createInterface({input: analysis.stdout});
  await ready(analysis, listener => lines.on('line', listener), line => JSON.parse(line).port === config.analysisPort);
  watch(analysis);
  const web = spawn(process.execPath, [join(projectRoot, 'scripts/release-web-worker.mjs'), configFile],
    {cwd: join(projectRoot, 'apps/web'), stdio: ['ignore', 'inherit', 'inherit', 'ipc']});
  children.push(web);
  await ready(web, listener => web.on('message', listener), message => message?.ready === true);
  watch(web);
  console.log(`FS_elem готов: http://${config.host}:${config.port}/analysis`);
  console.log(`Профиль: ${profile} · ${recipe}`);
  console.log('Для остановки нажмите Ctrl+C.');
  if (openBrowser) {
    const opened = spawnSync('/usr/bin/open', [`http://${config.host}:${config.port}/analysis`],
      {stdio: 'ignore', timeout: 5000});
    if (opened.error || opened.status !== 0) console.error('Откройте адрес выше в браузере.');
  }
} catch (error) {
  console.error(error.message);
  await stop(1);
}
