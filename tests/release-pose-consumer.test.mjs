import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {join, resolve} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

const root = process.env.FS_ELEM_RELEASE_ROOT ? resolve(process.env.FS_ELEM_RELEASE_ROOT)
  : fileURLToPath(new URL('../', import.meta.url));
const fixture = JSON.parse(await readFile(new URL('./release-fixtures-v1.json', import.meta.url)));
const {normalizePose, normalizeResult} = await import(pathToFileURL(join(root, 'apps/web/lib/analysis-client.mjs')));
const {contentRect, drawablePose, nearestPoseFrame} = await import(pathToFileURL(join(root, 'apps/web/lib/pose-overlay.mjs')));
const id = fixture.pose.jobId, sha = fixture.pose.source.sha256;
const pose = normalizePose(fixture.pose, id, sha);
const near = time => {
  const frame = nearestPoseFrame(pose.frames, time, pose.maxTimeDelta);
  return frame && Math.abs(frame.time - time) <= frame.tolerance + 1e-9 ? frame : null;
};
const close = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-10,
  `${actual} differs from hand-derived ${expected}`);

test('consumer contain mapping preserves letterbox and confidence gaps', () => {
  const expected = fixture.handDerivedCases[0];
  const rect = contentRect(400, 400, pose.geometry.width, pose.geometry.height);
  assert.deepEqual(rect, expected.expectedImageRect);
  const frame = near(expected.seekTimeSeconds);
  assert.equal(frame.time, 0.50007); // Actual PTS, not frameIndex/fps = 0.5.
  const drawable = drawablePose(frame, pose.links, pose.geometry, rect, pose.minConfidence);
  assert.equal(drawable.points.length, 1);
  assert.equal(drawable.points[0].index, 5);
  close(drawable.points[0].x, expected.expectedLeftShoulderCanvas.x);
  close(drawable.points[0].y, expected.expectedLeftShoulderCanvas.y);
  assert.equal(drawable.links.length, 0); // Do not bridge a confidence=.29 elbow.
});

test('consumer hides dense gaps and leaves an all-null sparse sample empty', () => {
  assert.equal(near(0.526), null);
  assert.equal(near(0.95).time, 1.011);
  const frame = near(1.02);
  assert.equal(frame.time, 1.011);
  assert.equal(drawablePose(frame, pose.links, pose.geometry,
    contentRect(400, 400, 1920, 1080), pose.minConfidence).points.length, 0);
  assert.equal(near(1.08), null);
});

test('consumer rejects another source/job and unordered actual PTS', () => {
  assert.throws(() => normalizePose(fixture.pose, id, 'b'.repeat(64)));
  assert.throws(() => normalizePose(fixture.pose, 'another-job', sha));
  assert.throws(() => normalizePose({...fixture.pose, frames: [...fixture.pose.frames].reverse()}, id, sha));
});

test('display-oriented portrait pixels are not rotated twice', () => {
  const expected = fixture.handDerivedCases[4];
  const raw = structuredClone(fixture.pose);
  Object.assign(raw.source, expected.sourcePatch);
  raw.frames[0].points[5] = expected.point;
  const normalized = normalizePose(raw, id, sha);
  assert.equal(normalized.geometry.rotation, 0);
  const rect = contentRect(400, 400, normalized.geometry.width, normalized.geometry.height);
  assert.deepEqual(rect, expected.expectedImageRect);
  const drawable = drawablePose(normalized.frames[0], normalized.links, normalized.geometry, rect, .3);
  close(drawable.points[0].x, 143.75);
  close(drawable.points[0].y, 100);
});

test('result consumer keeps Axel abstention and binds empty success to its source', () => {
  const raw = {schemaVersion: 1, jobId: id, source: fixture.pose.source,
    limitations: ['synthetic fixture only'], events: [], noEvents: true};
  assert.deepEqual(normalizeResult(raw, id, sha).events, []);
  raw.events = fixture.nominalDefinitionCases.map((row, i) => ({...row,
    id: String(i), family: 'axel', startSeconds: i, endSeconds: i + .4}));
  assert.deepEqual(normalizeResult(raw, id, sha).events.map(x => x.label), ['1A', '2A', 'Axel']);
  assert.throws(() => normalizeResult(raw, id, 'b'.repeat(64)));
});
