// Own controller IPC closes when its parent dies; keep the existing UI worker unchanged.
let stopping = false;
function shutdown() {
  if (stopping) return;
  stopping = true;
  const deadline = setTimeout(() => process.exit(1), 3000);
  deadline.unref();
  if (process.listenerCount('SIGTERM')) process.emit('SIGTERM');
  else process.exit(0);
}
if (!process.send) throw new Error('Release UI worker requires its own controller IPC');
process.on('disconnect', shutdown);
process.on('message', message => { if (message?.type === 'shutdown') shutdown(); });
const {main} = await import('./release-web-worker.mjs');
await main().catch(error => {console.error(error.message); process.exit(1);});
