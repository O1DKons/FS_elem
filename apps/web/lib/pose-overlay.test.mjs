import test from 'node:test';
import assert from 'node:assert/strict';
import {
  contentRect,
  transformPoint,
  nearestPoseFrame,
  drawablePose,
} from './pose-overlay.mjs';

test('letterbox preserves source aspect ratio in landscape and portrait containers', () => {
  const landscape = contentRect(1000, 600, 1920, 1080);
  for (const [key, value] of Object.entries({
    x: 0,
    y: 18.75,
    width: 1000,
    height: 562.5,
  }))
    assert.ok(Math.abs(landscape[key] - value) < 1e-8);
  assert.deepEqual(contentRect(800, 450, 540, 960), {
    x: 273.4375,
    y: 0,
    width: 253.125,
    height: 450,
  });
});
test('source pixels map to the visible content, independently of canvas size', () => {
  const rect = contentRect(800, 450, 540, 960);
  assert.deepEqual(
    transformPoint(
      { x: 270, y: 480 },
      { width: 540, height: 960, rotation: 0 },
      rect,
    ),
    { x: 400, y: 225 },
  );
  assert.deepEqual(
    transformPoint(
      { x: 0, y: 0 },
      { width: 540, height: 960, rotation: 0 },
      rect,
    ),
    { x: 273.4375, y: 0 },
  );
});
test('clockwise source rotation transforms points before letterboxing', () => {
  const rect = { x: 10, y: 20, width: 200, height: 100 };
  assert.deepEqual(
    transformPoint(
      { x: 25, y: 50 },
      { width: 100, height: 200, rotation: 90 },
      rect,
    ),
    { x: 160, y: 45 },
  );
  assert.deepEqual(
    transformPoint(
      { x: 25, y: 50 },
      { width: 100, height: 200, rotation: 180 },
      rect,
    ),
    { x: 160, y: 95 },
  );
  assert.deepEqual(
    transformPoint(
      { x: 25, y: 50 },
      { width: 100, height: 200, rotation: 270 },
      rect,
    ),
    { x: 60, y: 95 },
  );
});
test('sparse pose does not persist across absent time ranges or interpolate', () => {
  const frames = [
    { time: 0.1, points: [] },
    { time: 0.2, points: [] },
    { time: 2, points: [] },
  ];
  assert.equal(nearestPoseFrame(frames, 0.19, 0.04), frames[1]);
  assert.equal(nearestPoseFrame(frames, 1, 0.04), null);
  assert.equal(nearestPoseFrame(frames, 0, 0.04), null);
  assert.equal(nearestPoseFrame([], 1, 0.04), null);
});
test('null, weak, nonfinite and outside points do not produce joints or links', () => {
  const points = [
    { x: 10, y: 10, confidence: 0.9 },
    null,
    { x: 20, y: 20, confidence: 0.1 },
    { x: 30, y: 30, confidence: 0.8 },
    { x: Infinity, y: 2, confidence: 0.9 },
    { x: 101, y: 1, confidence: 1 },
  ];
  const pose = drawablePose(
    { time: 1, points },
    [
      [0, 3],
      [0, 1],
      [0, 2],
      [0, 4],
      [0, 5],
    ],
    { width: 100, height: 100, rotation: 0 },
    { x: 0, y: 0, width: 200, height: 200 },
    0.3,
  );
  assert.deepEqual(pose.points, [
    { index: 0, x: 20, y: 20 },
    { index: 3, x: 60, y: 60 },
  ]);
  assert.equal(pose.links.length, 1);
});
test('invalid geometry and invalid time tolerance are rejected', () => {
  assert.equal(contentRect(0, 10, 10, 10), null);
  assert.equal(
    transformPoint(
      { x: 1, y: 1 },
      { width: 0, height: 1, rotation: 0 },
      { x: 0, y: 0, width: 1, height: 1 },
    ),
    null,
  );
  assert.equal(
    transformPoint(
      { x: 1, y: 1 },
      { width: 10, height: 10, rotation: 45 },
      { x: 0, y: 0, width: 1, height: 1 },
    ),
    null,
  );
  assert.equal(nearestPoseFrame([{ time: 1 }], 1, -1), null);
});
