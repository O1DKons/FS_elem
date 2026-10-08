// Main close upper bound ~19s plus server/IPC overhead; separate UI cleanup.
export const API_GRACE_MS = 24000;
export const UI_GRACE_MS = 4000;

// Only call with a child created and retained by this controller.
// API owns its backend job trees; this helper never enumerates/kills processes by name.
export async function stopOwnedChild(child, cooperative = false, waitMs = 12000, fallbackMs = 3000) {
  if (!child.pid || child.exitCode !== null || child.signalCode !== null) return true;
  const wait = milliseconds => new Promise(resolve => {
    let timer;
    const ended = () => { clearTimeout(timer); child.off('error', failed); resolve(true); };
    const failed = () => { clearTimeout(timer); child.off('close', ended); resolve(false); };
    child.once('close', ended);
    child.once('error', failed);
    timer = setTimeout(() => { child.off('close', ended); child.off('error', failed); resolve(false); }, milliseconds);
  });
  const orderly = wait(waitMs);
  if (cooperative === 'ipc' && child.connected) {
    child.send({ type: 'shutdown' }, () => {});
  } else if ((cooperative === true || cooperative === 'stdin') && child.stdin) {
    child.stdin.on('error', () => {}); // A concurrent child exit closes its private pipe.
    child.stdin.end(JSON.stringify({ type: 'shutdown' }) + '\n', 'utf8');
  } else child.kill('SIGTERM');
  if (await orderly) return true;
  if (child.exitCode !== null || child.signalCode !== null) return true;
  const ended = wait(fallbackMs);
  child.kill('SIGKILL');
  return await ended;
}
