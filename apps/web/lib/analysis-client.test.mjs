import test from 'node:test';
import assert from 'node:assert/strict';
import {
  createAnalysisClient,
  AnalysisHttpError,
  normalizePose,
  normalizeResult,
} from './analysis-client.mjs';
const sha = 'a'.repeat(64);
const job = {
  schemaVersion: 1,
  jobId: 'job-1',
  state: 'queued',
  source: { sha256: sha },
  progress: {
    stage: 'queued',
    percent: null,
    currentFrame: null,
    totalFrames: null,
  },
  error: null,
};
const source = { sha256: sha, width: 540, height: 960, rotationDegrees: 90 };
const pose = {
  schemaVersion: 1,
  jobId: 'job-1',
  source,
  coordinateSpace: 'displayed-source-pixels',
  keypointNames: Array.from({ length: 23 }, (_, i) => 'p' + i),
  edges: [[0, 1]],
  maxNearestSeconds: { sparse: 0.065, dense: 0.025 },
  frames: [{ timeSeconds: 1, density: 'dense', points: Array(23).fill(null) }],
};
test('uploads exact bytes with encoded name and forwards abort signal', async () => {
  const file = new File(['video bytes'], 'тест 1.mp4');
  const controller = new AbortController();
  const client = createAnalysisClient(async (url, options) => {
    assert.equal(url, '/api/analysis/jobs');
    assert.equal(options.method, 'POST');
    assert.equal(options.body, file);
    assert.equal(options.signal, controller.signal);
    assert.equal(options.headers['X-Filename'], encodeURIComponent(file.name));
    return Response.json(job, { status: 202 });
  });
  assert.equal((await client.upload(file, controller.signal)).id, 'job-1');
});
test('server failures retain actionable message and HTTP code', async () => {
  const client = createAnalysisClient(async () =>
    Response.json(
      { error: { code: 'UNAVAILABLE', message: 'Модели не установлены' } },
      { status: 503 },
    ),
  );
  await assert.rejects(
    client.health(),
    (e) =>
      e instanceof AnalysisHttpError &&
      e.status === 503 &&
      e.message === 'Модели не установлены',
  );
});
test('display-oriented points are never rotated again from source metadata', () => {
  const normalized = normalizePose(pose, 'job-1', sha);
  assert.deepEqual(normalized.geometry, {
    width: 540,
    height: 960,
    rotation: 0,
  });
  assert.equal(normalized.frames[0].tolerance, 0.025);
});
test('pose rejects another job/source, malformed lengths and invalid coordinates', () => {
  assert.throws(() => normalizePose(pose, 'other', sha));
  assert.throws(() => normalizePose(pose, 'job-1', 'b'.repeat(64)));
  assert.throws(() =>
    normalizePose(
      { ...pose, frames: [{ ...pose.frames[0], points: [null] }] },
      'job-1',
      sha,
    ),
  );
  assert.throws(() =>
    normalizePose(
      {
        ...pose,
        frames: [
          {
            ...pose.frames[0],
            points: [{ x: NaN, y: 2, confidence: 1 }, ...Array(22).fill(null)],
          },
        ],
      },
      'job-1',
      sha,
    ),
  );
});
test('abstention stays Axel with undefined nominal; no-events remains empty', () => {
  const result = {
    schemaVersion: 1,
    jobId: 'job-1',
    source,
    events: [
      {
        id: 'c1',
        family: 'axel',
        nominal: null,
        startSeconds: 1,
        endSeconds: 1.4,
        nominalReason: 'insufficient_evidence',
      },
    ],
    limitations: [],
  };
  assert.equal(normalizeResult(result, 'job-1', sha).events[0].label, 'Axel');
  assert.equal(
    normalizeResult({ ...result, events: [] }, 'job-1', sha).events.length,
    0,
  );
  assert.throws(() =>
    normalizeResult(
      { ...result, events: [{ ...result.events[0], nominal: '3A' }] },
      'job-1',
      sha,
    ),
  );
});
test('result and pose calls URL-encode opaque IDs; cancel uses DELETE', async () => {
  const calls = [];
  const client = createAnalysisClient(async (url, options) => {
    calls.push([url, options.method]);
    return Response.json({ ...job, jobId: 'a/b', state: 'cancelled' });
  });
  assert.equal((await client.cancel('a/b')).status, 'cancelled');
  assert.deepEqual(calls, [['/api/analysis/jobs/a%2Fb', 'DELETE']]);
});

test('saved jobs retain source identity and server timestamps without upload', async () => {
  const saved = {
    ...job,
    state: 'succeeded',
    createdAt: '2026-10-03T06:47:44.996Z',
    updatedAt: '2026-10-03T06:59:48.433Z',
    source: { sha256: sha, filename: 'program.mp4', sizeBytes: 78192638 },
  };
  const client = createAnalysisClient(async (url, options) => {
    assert.equal(
      options.method ?? 'GET',
      'GET',
      'opening an existing job must not upload',
    );
    return Response.json(saved);
  });
  const value = await client.job('job-1');
  assert.equal(value.filename, 'program.mp4');
  assert.equal(value.sizeBytes, 78192638);
  assert.equal(value.createdAt, saved.createdAt);
  assert.equal(value.updatedAt, saved.updatedAt);
});

test('nominal turns remain definitions and contradictory values are rejected', () => {
  const result = {
    schemaVersion: 1,
    jobId: 'job-1',
    source,
    limitations: [],
    events: [
      {
        id: 'c1',
        family: 'axel',
        nominal: '1A',
        nominalRevolutions: 1.5,
        startSeconds: 1,
        endSeconds: 1.4,
      },
      {
        id: 'c2',
        family: 'axel',
        nominal: '2A',
        nominalRevolutions: 2.5,
        startSeconds: 2,
        endSeconds: 2.4,
      },
      {
        id: 'c3',
        family: 'axel',
        nominal: null,
        nominalRevolutions: null,
        startSeconds: 3,
        endSeconds: 3.4,
      },
    ],
  };
  assert.deepEqual(
    normalizeResult(result, 'job-1', sha).events.map(
      (e) => e.nominalRevolutions,
    ),
    [1.5, 2.5, null],
  );
  assert.throws(() =>
    normalizeResult(
      { ...result, events: [{ ...result.events[0], nominalRevolutions: 2.5 }] },
      'job-1',
      sha,
    ),
  );
});

test('elapsed snapshot is optional and cannot become an invalid duration', async () => {
  const read = async (elapsedSeconds) => {
    const client = createAnalysisClient(async () =>
      Response.json({ ...job, elapsedSeconds }),
    );
    return client.job('job-1');
  };
  assert.equal((await read(45)).elapsedSeconds, 45);
  assert.equal((await read(undefined)).elapsedSeconds, undefined);
  assert.equal((await read(null)).elapsedSeconds, null);
  assert.equal((await read(-1)).elapsedSeconds, null);
});
