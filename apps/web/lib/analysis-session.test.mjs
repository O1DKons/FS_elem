import test from 'node:test';
import assert from 'node:assert/strict';
const session = await import('./analysis-session.mjs').catch(() => ({}));
const id = 'f042611d-5aeb-4548-b3ab-43b2df89ad74';

test('completed task duration stays frozen when reopened later', () => {
  assert.equal(typeof session.elapsedJobSeconds, 'function');
  const job = {
    status: 'completed',
    createdAt: '2026-10-03T12:00:00Z',
    updatedAt: '2026-10-03T12:01:30Z',
  };
  assert.equal(
    session.elapsedJobSeconds(job, Date.parse('2026-10-04T12:00:00Z')),
    90,
  );
  assert.equal(
    session.elapsedJobSeconds(
      { ...job, status: 'failed' },
      Date.parse('2026-10-04T12:00:00Z'),
    ),
    90,
  );
});

test('running elapsed includes waiting; invalid or future time is unknown', () => {
  assert.equal(typeof session.elapsedJobSeconds, 'function');
  const now = Date.parse('2026-10-03T12:00:45Z');
  const job = {
    status: 'running',
    createdAt: '2026-10-03T12:00:00Z',
    updatedAt: '2026-10-03T12:00:05Z',
    elapsedSeconds: 45,
  };
  assert.equal(session.elapsedJobSeconds(job, now), 45);
  assert.equal(
    session.elapsedJobSeconds(
      { ...job, createdAt: 'invalid', elapsedSeconds: null },
      now,
    ),
    null,
  );
  assert.equal(
    session.elapsedJobSeconds(
      { ...job, createdAt: '2026-10-03T12:01:00Z', elapsedSeconds: undefined },
      now,
    ),
    null,
  );
  assert.equal(
    session.elapsedJobSeconds(
      {
        ...job,
        status: 'cancelled',
        updatedAt: null,
        elapsedSeconds: undefined,
      },
      now,
    ),
    null,
  );
});

test('saved link stays on the same local route and media cannot accept a path', () => {
  assert.equal(typeof session.jobLocation, 'function');
  assert.equal(
    session.jobLocation('http://localhost:5174/analysis?view=full#jump', id),
    '/analysis?view=full&job=' + id + '#jump',
  );
  assert.equal(session.jobIdFromSearch('?job=' + id), id);
  assert.equal(session.jobIdFromSearch('?job=../../private'), null);
  assert.equal(session.jobIdFromSearch('?job=' + id + '&job=another'), null);
  assert.equal(session.mediaPath(id), '/api/analysis/jobs/' + id + '/media');
  assert.throws(() => session.mediaPath('../../private'));
});

test('denied storage does not prevent opening a job link', () => {
  assert.equal(typeof session.readRememberedJob, 'function');
  const denied = {
    getItem() {
      throw Error('blocked');
    },
    setItem() {
      throw Error('blocked');
    },
  };
  assert.doesNotThrow(() => session.rememberJob(id, denied));
  assert.equal(session.readRememberedJob(denied), null);
  assert.equal(session.jobIdFromSearch('?job=' + id), id);
  let stored;
  const storage = {
    getItem() {
      return stored;
    },
    setItem(key, value) {
      stored = value;
    },
  };
  session.rememberJob(id, storage);
  assert.equal(session.readRememberedJob(storage), id);
  assert.equal(
    stored,
    id,
    'store only an opaque job identifier, not video or result data',
  );
});
