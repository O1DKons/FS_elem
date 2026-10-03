export type Point = { x: number; y: number; confidence: number };
export type PoseFrame = { time: number; points: (Point | null)[] };
export type Geometry = {
  width: number;
  height: number;
  rotation: 0 | 90 | 180 | 270;
};
export type ContentRect = {
  x: number;
  y: number;
  width: number;
  height: number;
};
export function contentRect(
  containerWidth: number,
  containerHeight: number,
  imageWidth: number,
  imageHeight: number,
): ContentRect | null;
export function transformPoint(
  point: Point | null,
  geometry: Geometry,
  rect: ContentRect | null,
): { x: number; y: number } | null;
export function nearestPoseFrame<T extends { time: number }>(
  frames: T[],
  time: number,
  tolerance: number,
): T | null;
export function drawablePose(
  frame: PoseFrame,
  links: [number, number][],
  geometry: Geometry,
  rect: ContentRect,
  minConfidence: number,
): {
  points: { index: number; x: number; y: number }[];
  links: [
    { index: number; x: number; y: number },
    { index: number; x: number; y: number },
  ][];
};
