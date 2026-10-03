import type { AnalysisJob } from './analysis-types';
export function jobIdFromSearch(search: string): string | null;
export function readRememberedJob(
  storage: Pick<Storage, 'getItem'>,
): string | null;
export function rememberJob(
  id: string,
  storage: Pick<Storage, 'setItem'>,
): void;
export function jobLocation(href: string, id: string | null): string;
export function mediaPath(id: string): string;
export function elapsedJobSeconds(
  job: Pick<
    AnalysisJob,
    'status' | 'createdAt' | 'updatedAt' | 'elapsedSeconds'
  >,
): number | null;
