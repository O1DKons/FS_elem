const storageKey = 'fs-elem-last-analysis-v1';
const canonicalId = (id) =>
  typeof id === 'string' &&
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(id);

export function jobIdFromSearch(search) {
  const values = new URLSearchParams(search).getAll('job');
  return values.length === 1 && canonicalId(values[0]) ? values[0] : null;
}
export function readRememberedJob(storage) {
  try {
    const id = storage.getItem(storageKey);
    return canonicalId(id) ? id : null;
  } catch {
    return null;
  }
}
export function rememberJob(id, storage) {
  if (!canonicalId(id)) return;
  try {
    storage.setItem(storageKey, id);
  } catch {
    /* URL reopening still works. */
  }
}
export function jobLocation(href, id) {
  const url = new URL(href);
  if (id === null) url.searchParams.delete('job');
  else {
    if (!canonicalId(id)) throw Error('Некорректная ссылка на анализ.');
    url.searchParams.set('job', id);
  }
  return url.pathname + url.search + url.hash;
}
export function mediaPath(id) {
  if (!canonicalId(id)) throw Error('Некорректная ссылка на анализ.');
  return '/api/analysis/jobs/' + id + '/media';
}
export function elapsedJobSeconds(job) {
  if (job.elapsedSeconds !== undefined)
    return Number.isFinite(job.elapsedSeconds) && job.elapsedSeconds >= 0
      ? job.elapsedSeconds
      : null;
  // Old servers expose exact terminal timestamps, but not an active elapsed snapshot.
  if (!['completed', 'failed', 'cancelled'].includes(job.status)) return null;
  const stamp = (value) =>
    typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(value)
      ? Date.parse(value)
      : NaN;
  const start = stamp(job.createdAt),
    end = stamp(job.updatedAt);
  return Number.isFinite(start) && Number.isFinite(end) && end >= start
    ? (end - start) / 1000
    : null;
}
