import type {
  AnalysisJob,
  AnalysisPose,
  AnalysisResult,
} from './analysis-types';
export class AnalysisHttpError extends Error {
  status: number;
  constructor(message: string, status: number);
}
export function normalizeResult(
  data: unknown,
  id: string,
  sha: string,
): AnalysisResult;
export function normalizePose(
  data: unknown,
  id: string,
  sha: string,
): AnalysisPose;
export type AnalysisHealth = {
  inferenceAvailable: boolean;
  issues: string[];
  activeJobId: string | null;
};
export function createAnalysisClient(fetcher?: typeof fetch): {
  health(signal?: AbortSignal): Promise<AnalysisHealth>;
  upload(file: File, signal?: AbortSignal): Promise<AnalysisJob>;
  job(id: string, signal?: AbortSignal): Promise<AnalysisJob>;
  cancel(id: string, signal?: AbortSignal): Promise<AnalysisJob>;
  result(
    id: string,
    sha: string,
    signal?: AbortSignal,
  ): Promise<AnalysisResult>;
  pose(id: string, sha: string, signal?: AbortSignal): Promise<AnalysisPose>;
};
