import {join} from 'node:path';
import {pathToFileURL, fileURLToPath} from 'node:url';

// Keep the normal upload/result/cancel API in front of the compiled UI.
export function installReleaseAdapter(server, api) {
  const listeners = server.listeners('request');
  if (listeners.length !== 1) throw Error('Unexpected production request listener');
  server.removeListener('request', listeners[0]);
  server.on('request', (req, res) => api(req, res, () => listeners[0].call(server, req, res)));
}

async function main() {
  const {loadConfig, projectRoot} = await import('./config.mjs');
  const {openStore} = await import('../server/store.mjs');
  const {createApi} = await import('../server/api.mjs');
  const {startProdServer} = await import(pathToFileURL(join(projectRoot, 'apps/web/node_modules/vinext/dist/server/prod-server.js')));
  const config = loadConfig(projectRoot, process.argv[2]);
  const store = openStore(config.dataDir);
  let server, stopping = false;
  const stop = (code = 0) => {
    if (stopping) return;
    stopping = true;
    if (!server) {store.close(); process.exit(code);}
    server.close(() => {store.close(); process.exit(code);});
    server.closeAllConnections();
  };
  process.once('disconnect', () => stop());
  process.once('SIGINT', () => stop());
  process.once('SIGTERM', () => stop());
  try {
    const started = await startProdServer({host: config.host, port: config.port,
      outDir: join(projectRoot, 'apps/web/dist'), silent: true});
    server = started.server;
    if (started.port !== config.port) throw Error('Unexpected production port');
    installReleaseAdapter(server, createApi(store, config));
    process.send?.({ready: true, port: started.port, mode: 'production'});
  } catch (error) {console.error(error.message); stop(1);}
}

if (process.argv[1] === fileURLToPath(import.meta.url))
  main().catch(error => {console.error(error.message); process.exit(1);});
