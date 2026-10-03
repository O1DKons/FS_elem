import type { Geometry, PoseFrame } from './pose-overlay.mjs';

// UI view model. The API adapter is the only boundary that normalizes server data.
export type AnalysisPose = {
  geometry: Geometry;
  links: [number, number][];
  frames: (PoseFrame & { tolerance: number })[];
  minConfidence: number;
  maxTimeDelta: number;
};
export type AnalysisEvent = {
  id: string;
  start: number;
  end: number;
  label: 'Axel' | '1A' | '2A' | 'unknown';
  reason?: string;
  nominalRevolutions: 1.5 | 2.5 | null;
};
export type AnalysisJob = {
  id: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  stage: string;
  progress: number | null;
  currentFrame: number | null;
  totalFrames: number | null;
  sourceSha256: string;
  filename: string | null;
  sizeBytes: number | null;
  createdAt: string | null;
  updatedAt: string | null;
  elapsedSeconds?: number | null;
  error?: string;
};
export type AnalysisResult = {
  events: AnalysisEvent[];
  warnings: string[];
  sourceSha256: string;
};
