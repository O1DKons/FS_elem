#!/usr/bin/env node
import {spawn, spawnSync} from 'node:child_process';
import {createInterface} from 'node:readline';
import {join} from 'node:path';
import {mkdirSync, writeFileSync, existsSync, readFileSync} from 'node:fs';
import {loadConfig, projectRoot} from './config.mjs';
import {profile as nativeProfile, releaseRecipeName, requireWindowsRecipe, browserCommand} from './release-platform.mjs';
import {stopOwnedChild, API_GRACE_MS, UI_GRACE_MS} from './release-control.mjs';
import {requireDesktopReady, prepareDesktopConfig, attachDesktopControl} from './windows-bundle.mjs';

const children = [];
let stopping = false;
let desktop = false;
let firstFailure = null;
function reportFailure(error) {
  if (firstFailure) return;
  firstFailure = error;
  if (desktop) console.log(JSON.stringify({type: 'error', stage: 'start', message: error.message, details: error.details}));
  console.error(error.message);
}
function serviceDiagnostic(child, service) {
  let tail = '';
  child.stderr?.setEncoding('utf8');
  child.stderr?.on('data', text => {
    tail = (tail + text).slice(-4096);
    process.stderr.write(text); // Preserve the raw stderr log as well as a bounded cause.
  });
  return (reason, details = {}) => {
    const stderrTail = tail.slice(-2048).trim();
    const error = Error(service + ': ' + reason + (stderrTail ? '\n' + stderrTail : ''));
    error.details = {service, pid: child.pid ?? null, ...details, stderrTail};
    return error;
  };
}
async function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  const stopped = await Promise.all(children.map(({child, channel}) => stopOwnedChild(child, channel, channel === 'stdin' ? API_GRACE_MS : UI_GRACE_MS)));
  if (stopped.some(result => !result)) {
    console.error('Не удалось подтвердить завершение собственного сервиса в установленный срок.');
    code = 1;
  }
  if (desktop) console.log(JSON.stringify({type: 'stopped', exitCode: code}));
  process.exit(code);
}
process.on('SIGINT', () => stop());
process.on('SIGTERM', () => stop());
function ready(child, subscribe, accept, diagnostic) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const cleanup = () => {clearTimeout(timer);child.off('error', failedSpawn);child.off('exit', failedExit);};
    const fail = error => {if (settled) return;settled = true;cleanup();reject(error);};
    const failedSpawn = error => fail(diagnostic('spawn failed: ' + error.message, {spawnCode: error.code ?? null}));
    const failedExit = (code, signal) => fail(diagnostic('exited before ready (code=' + code + ', signal=' + signal + ')', {exitCode: code, signal}));
    const timer = setTimeout(() => fail(diagnostic('readiness timed out after 15000 ms')), 15000);
    child.once('error', failedSpawn);
    child.once('exit', failedExit);
    subscribe(value => {
      if (settled) return;
      try {
        if (!accept(value)) return;
        settled = true;cleanup();
        resolve();
      } catch (error) {fail(error);}
    });
  });
}
function watch(child, diagnostic) {
  child.on('exit', (code, signal) => {
    if (!stopping) {reportFailure(diagnostic('stopped unexpectedly (code=' + code + ', signal=' + signal + ')', {exitCode: code, signal}));stop(1);}
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
    if (args[i] === '--desktop' && !desktop) {desktop = true; continue;}
    if (!['--config', '--profile', '--max-wall-seconds'].includes(args[i]) || !args[i + 1] || args[i] in options)
      throw Error('Usage: node scripts/start-release.mjs [--desktop] [--open] [--profile ort4|ort2] [--config web-config.json] [--max-wall-seconds 1..5400]');
    options[args[i]] = args[++i];
  }
  const maxWallSeconds = Number(options['--max-wall-seconds'] ?? 5400);
  if (!Number.isInteger(maxWallSeconds) || maxWallSeconds < 1 || maxWallSeconds > 5400)
    throw Error('Analysis deadline must be an integer from 1 to 5400 seconds');
  const profile = options['--profile'] ?? 'ort4';
  if (!['ort4', 'ort2'].includes(profile)) throw Error('Release profile must be ort4 or ort2');
  const native = nativeProfile();
  if (desktop && native.id !== 'windows-x64') throw Error('Desktop bundle requires Windows 10/11 x64.');
  if (desktop) attachDesktopControl(process.stdin, () => stop());
  const recipe = join(projectRoot, 'configs', releaseRecipeName(native.id, profile));
  if (!existsSync(recipe)) throw Error('В пакете отсутствует профиль анализа. Распакуйте полный пакет FS_elem.');
  const pythonRelative = ['.runtime', 'venv-science', ...native.pythonParts].join('/');
  const python = join(projectRoot, '.runtime', 'venv-science', ...native.pythonParts);
  if (!existsSync(python))
    throw Error(desktop ? 'Пакет FS_elem неполон. Переустановите приложение.' : 'Первоначальная настройка FS_elem ещё не выполнена. Запустите npm run setup:release с Python 3.12 и 3.9; команды в docs/release/installation.md.');
  if (!existsSync(join(projectRoot, 'apps/web/dist/server/index.js')) ||
      !existsSync(join(projectRoot, 'apps/web/dist/client')))
    throw Error(desktop ? 'Интерфейс FS_elem отсутствует. Переустановите приложение.' : 'Готовый интерфейс отсутствует. Выполните первоначальную настройку: docs/release/installation.md.');
  if (desktop) requireDesktopReady(projectRoot);
  else {
    const checked = spawnSync(process.execPath, [join(projectRoot, 'scripts/setup-release.mjs'), '--check',
      '--science-python', python], {stdio: 'inherit', windowsHide: true});
    if (checked.error || checked.status !== 0) throw Error('Зависимости FS_elem не прошли проверку. Выполните настройку: docs/release/installation.md.');
  }
  if (native.id === 'windows-x64') {
    const manifest = JSON.parse(readFileSync(join(projectRoot, 'assets/models/manifest-release-v1.json'), 'utf8'));
    requireWindowsRecipe(JSON.parse(readFileSync(recipe, 'utf8')), manifest.platforms?.['windows-x64']);
  }
  const defaultConfig = join(projectRoot, '.runtime/release-web.json');
  if (!desktop && !options['--config'] && !existsSync(defaultConfig)) {
    mkdirSync(join(projectRoot, '.runtime'), {recursive: true});
    writeFileSync(defaultConfig, JSON.stringify({host: '127.0.0.1', port: 5174, analysisPort: 5175,
      python: pythonRelative, dataDir: '.runtime/data'}, null, 2) + '\n', {flag: 'wx'});
  }
  const configFile = desktop ? prepareDesktopConfig(projectRoot, options['--config']) : options['--config'] ?? defaultConfig;
  const config = loadConfig(projectRoot, configFile);
  const analysis = spawn(python, [join(projectRoot, 'services/analysis/server.py'), '--port', String(config.analysisPort),
    '--config', recipe, '--jobs', desktop ? config.jobsDir : join(projectRoot, '.runtime/jobs'),
    '--max-wall-seconds', String(maxWallSeconds)],
    {cwd: projectRoot, stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true,
      env: {...process.env, FS_ELEM_CONTROL_STDIN: '1', PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1'}});
  children.push({child: analysis, channel: 'stdin'});
  const analysisDiagnostic = serviceDiagnostic(analysis, 'analysis API');
  const lines = createInterface({input: analysis.stdout});
  if (desktop) lines.on('line', line => console.log(line));
  await ready(analysis, listener => lines.on('line', listener), line => {
    try { return JSON.parse(line).port === config.analysisPort; }
    catch (error) { if (desktop) return false; throw error; }
  }, analysisDiagnostic);
  if (stopping) throw Error('Desktop startup cancelled');
  watch(analysis, analysisDiagnostic);
  const web = spawn(process.execPath, [join(projectRoot, 'scripts/release-owned-web-worker.mjs'), configFile],
    {cwd: join(projectRoot, 'apps/web'), stdio: ['ignore', 'inherit', 'pipe', 'ipc'], windowsHide: true});
  children.push({child: web, channel: 'ipc'});
  const webDiagnostic = serviceDiagnostic(web, 'web UI');
  await ready(web, listener => web.on('message', listener), message => message?.ready === true, webDiagnostic);
  watch(web, webDiagnostic);
  if (stopping) throw Error('Desktop startup cancelled');
  if (desktop) console.log(JSON.stringify({type: 'ready', url: `http://${config.host}:${config.port}/analysis`, profile}));
  else {
    console.log(`FS_elem готов: http://${config.host}:${config.port}/analysis`);
    console.log(`Профиль: ${profile} · ${recipe}`);
    console.log('Для остановки нажмите Ctrl+C.');
  }
  if (openBrowser) {
    const [executable, argv] = browserCommand(`http://${config.host}:${config.port}/analysis`);
    const opened = spawnSync(executable, argv, {stdio: 'ignore', timeout: 5000, shell: false, windowsHide: true});
    if (opened.error || opened.status !== 0) console.error('Откройте адрес выше в браузере.');
  }
} catch (error) {
  reportFailure(error);
  await stop(1);
}
