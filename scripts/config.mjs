import {existsSync, readFileSync} from 'node:fs';
import {resolve, join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {resolveExecutable} from './release-platform.mjs';
export const projectRoot = fileURLToPath(new URL('../', import.meta.url));
export function loadConfig(root = projectRoot, configFile) {
  const path = configFile ? resolve(root,configFile) : join(root,'config.local.json');
  if(configFile && !existsSync(path)) throw Error('Configuration file not found');
  const local = existsSync(path) ? JSON.parse(readFileSync(path, 'utf8')) : {};
  const c = {dataDir:'data/live', host:'127.0.0.1', port:5174, analysisPort:5175, python:existsSync(join(root, '.venv', ...(process.platform === 'win32' ? ['Scripts', 'python.exe'] : ['bin', 'python']))) ? join(root, '.venv', ...(process.platform === 'win32' ? ['Scripts', 'python.exe'] : ['bin', 'python'])) : (process.platform === 'win32' ? 'python' : 'python3'), ...local};
  if(c.host !== '127.0.0.1') throw Error('Only local access is supported');
  for(const k of ['port','analysisPort']) if(!Number.isInteger(c[k]) || c[k]<1024 || c[k]>65535) throw Error('Invalid port');
  if(c.port === c.analysisPort) throw Error('Ports must differ');
  for(const k of ['dataDir','python']) if(typeof c[k] !== 'string' || !c[k].trim()) throw Error(`Invalid ${k}`);
  return {...c, dataDir:resolve(root,c.dataDir),python:resolveExecutable(c.python,root)};
}
