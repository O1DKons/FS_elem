const positive = (value) => Number.isFinite(value) && value > 0;

export function contentRect(
  containerWidth,
  containerHeight,
  imageWidth,
  imageHeight,
) {
  if (
    ![containerWidth, containerHeight, imageWidth, imageHeight].every(positive)
  )
    return null;
  const scale = Math.min(
    containerWidth / imageWidth,
    containerHeight / imageHeight,
  );
  const width = imageWidth * scale,
    height = imageHeight * scale;
  return {
    x: (containerWidth - width) / 2,
    y: (containerHeight - height) / 2,
    width,
    height,
  };
}

// rotation is the clockwise display rotation of the source pixel coordinate space.
export function transformPoint(point, geometry, rect) {
  if (
    !point ||
    !rect ||
    !positive(geometry.width) ||
    !positive(geometry.height) ||
    ![0, 90, 180, 270].includes(geometry.rotation)
  )
    return null;
  if (
    ![point.x, point.y].every(Number.isFinite) ||
    point.x < 0 ||
    point.y < 0 ||
    point.x > geometry.width ||
    point.y > geometry.height
  )
    return null;
  let x = point.x / geometry.width,
    y = point.y / geometry.height;
  if (geometry.rotation === 90) [x, y] = [1 - y, x];
  else if (geometry.rotation === 180) [x, y] = [1 - x, 1 - y];
  else if (geometry.rotation === 270) [x, y] = [y, 1 - x];
  return { x: rect.x + x * rect.width, y: rect.y + y * rect.height };
}

// Frames must be sorted by source presentation time. Never hold or synthesize pose.
export function nearestPoseFrame(frames, time, tolerance) {
  if (
    !frames.length ||
    !Number.isFinite(time) ||
    !Number.isFinite(tolerance) ||
    tolerance < 0
  )
    return null;
  let lo = 0,
    hi = frames.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (frames[mid].time < time) lo = mid + 1;
    else hi = mid;
  }
  const before = frames[lo - 1],
    after = frames[lo];
  const candidate =
    before && (!after || time - before.time <= after.time - time)
      ? before
      : after;
  return candidate && Math.abs(candidate.time - time) <= tolerance + 1e-9
    ? candidate
    : null;
}

export function drawablePose(frame, links, geometry, rect, minConfidence) {
  const mapped = new Map();
  frame.points.forEach((point, index) => {
    if (
      !point ||
      !Number.isFinite(point.confidence) ||
      point.confidence < minConfidence
    )
      return;
    const xy = transformPoint(point, geometry, rect);
    if (xy) mapped.set(index, { index, ...xy });
  });
  return {
    points: [...mapped.values()],
    links: links.flatMap(([a, b]) =>
      mapped.has(a) && mapped.has(b) ? [[mapped.get(a), mapped.get(b)]] : [],
    ),
  };
}
