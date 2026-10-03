export class AnalysisHttpError extends Error {
  constructor(message, status) {
    super(message);
    this.name = 'AnalysisHttpError';
    this.status = status;
  }
}
const invalid = () => {
  throw new Error('Сервис вернул несовместимые данные анализа.');
};
const finite = Number.isFinite;
const shaValid = (sha) =>
  typeof sha === 'string' && /^[a-f0-9]{64}$/i.test(sha);
function binding(data, id, sha) {
  if (
    data?.schemaVersion !== 1 ||
    data.jobId !== id ||
    !shaValid(data.source?.sha256) ||
    data.source.sha256 !== sha
  )
    invalid();
}
function normalizeJob(data) {
  const states = {
    queued: 'queued',
    running: 'running',
    succeeded: 'completed',
    failed: 'failed',
    cancelled: 'cancelled',
  };
  if (
    data?.schemaVersion !== 1 ||
    typeof data.jobId !== 'string' ||
    !states[data.state] ||
    !shaValid(data.source?.sha256) ||
    typeof data.progress?.stage !== 'string'
  )
    invalid();
  const percent = data.progress.percent;
  if (percent !== null && (!finite(percent) || percent < 0 || percent > 100))
    invalid();
  return {
    id: data.jobId,
    status: states[data.state],
    stage: data.progress.stage,
    progress: percent,
    currentFrame: data.progress.currentFrame ?? null,
    totalFrames: data.progress.totalFrames ?? null,
    sourceSha256: data.source.sha256,
    filename:
      typeof data.source.filename === 'string' ? data.source.filename : null,
    sizeBytes:
      Number.isSafeInteger(data.source.sizeBytes) && data.source.sizeBytes > 0
        ? data.source.sizeBytes
        : null,
    createdAt: typeof data.createdAt === 'string' ? data.createdAt : null,
    updatedAt: typeof data.updatedAt === 'string' ? data.updatedAt : null,
    elapsedSeconds:
      data.elapsedSeconds === undefined
        ? undefined
        : finite(data.elapsedSeconds) && data.elapsedSeconds >= 0
          ? data.elapsedSeconds
          : null,
    error: data.error?.message,
  };
}
export function normalizeResult(data, id, sha) {
  binding(data, id, sha);
  if (!Array.isArray(data.events) || !Array.isArray(data.limitations))
    invalid();
  return {
    sourceSha256: sha,
    warnings: data.limitations.filter((x) => typeof x === 'string'),
    events: data.events.map((event) => {
      const nominalRevolutions = event.nominalRevolutions ?? null;
      const expectedRevolutions =
        event.nominal === '1A' ? 1.5 : event.nominal === '2A' ? 2.5 : null;
      if (
        typeof event.id !== 'string' ||
        event.family !== 'axel' ||
        ![null, '1A', '2A'].includes(event.nominal) ||
        !finite(event.startSeconds) ||
        !finite(event.endSeconds) ||
        event.startSeconds < 0 ||
        event.endSeconds < event.startSeconds ||
        (nominalRevolutions !== null &&
          nominalRevolutions !== expectedRevolutions)
      )
        invalid();
      return {
        id: event.id,
        start: event.startSeconds,
        end: event.endSeconds,
        label: event.nominal ?? 'Axel',
        reason: event.nominalReason,
        nominalRevolutions,
      };
    }),
  };
}
export function normalizePose(data, id, sha) {
  binding(data, id, sha);
  if (
    data.coordinateSpace !== 'displayed-source-pixels' ||
    !Number.isInteger(data.source.width) ||
    data.source.width <= 0 ||
    !Number.isInteger(data.source.height) ||
    data.source.height <= 0 ||
    !Array.isArray(data.keypointNames) ||
    data.keypointNames.length !== 23 ||
    !Array.isArray(data.edges) ||
    !Array.isArray(data.frames)
  )
    invalid();
  for (const edge of data.edges)
    if (
      !Array.isArray(edge) ||
      edge.length !== 2 ||
      !edge.every((i) => Number.isInteger(i) && i >= 0 && i < 23)
    )
      invalid();
  const limits = data.maxNearestSeconds;
  if (
    !limits ||
    !finite(limits.sparse) ||
    limits.sparse <= 0 ||
    limits.sparse > 0.065 ||
    !finite(limits.dense) ||
    limits.dense <= 0 ||
    limits.dense > 0.025
  )
    invalid();
  let last = -Infinity;
  const frames = data.frames.map((frame) => {
    if (
      !finite(frame.timeSeconds) ||
      frame.timeSeconds < 0 ||
      frame.timeSeconds <= last ||
      !['sparse', 'dense'].includes(frame.density) ||
      !Array.isArray(frame.points) ||
      frame.points.length !== 23
    )
      invalid();
    last = frame.timeSeconds;
    for (const p of frame.points)
      if (p !== null && (!p || ![p.x, p.y, p.confidence].every(finite)))
        invalid();
    return {
      time: frame.timeSeconds,
      points: frame.points,
      tolerance: limits[frame.density],
    };
  });
  // Source rotationDegrees is metadata. Exported geometry is already display-oriented.
  return {
    geometry: {
      width: data.source.width,
      height: data.source.height,
      rotation: 0,
    },
    links: data.edges,
    frames,
    minConfidence: 0.3,
    maxTimeDelta: limits.sparse,
  };
}
export function createAnalysisClient(fetcher = fetch) {
  async function request(path, options = {}) {
    const response = await fetcher(path, options);
    let data;
    try {
      data = await response.json();
    } catch {
      throw new AnalysisHttpError(
        'Сервис анализа вернул нечитаемый ответ.',
        response.status,
      );
    }
    if (!response.ok)
      throw new AnalysisHttpError(
        data?.error?.message || `Ошибка сервиса (${response.status})`,
        response.status,
      );
    return data;
  }
  const path = (id) => `/api/analysis/jobs/${encodeURIComponent(id)}`;
  return {
    async health(signal) {
      const data = await request('/api/analysis/health', { signal });
      if (
        typeof data.inferenceAvailable !== 'boolean' ||
        !Array.isArray(data.issues) ||
        !data.issues.every((issue) => typeof issue === 'string')
      )
        invalid();
      return data;
    },
    async upload(file, signal) {
      return normalizeJob(
        await request('/api/analysis/jobs', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/octet-stream',
            'X-Filename': encodeURIComponent(file.name),
          },
          body: file,
          signal,
        }),
      );
    },
    async job(id, signal) {
      const data = await request(path(id), { signal });
      if (data.jobId !== id) invalid();
      return normalizeJob(data);
    },
    async cancel(id, signal) {
      const data = await request(path(id), { method: 'DELETE', signal });
      if (data.jobId !== id) invalid();
      return normalizeJob(data);
    },
    async result(id, sha, signal) {
      return normalizeResult(
        await request(path(id) + '/result', { signal }),
        id,
        sha,
      );
    },
    async pose(id, sha, signal) {
      return normalizePose(
        await request(path(id) + '/pose', { signal }),
        id,
        sha,
      );
    },
  };
}
