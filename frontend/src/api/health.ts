import { useQuery } from '@tanstack/react-query';

import { apiRequest } from './client';

export interface DependencyStatus {
  status: 'ok' | 'error';
  error: string | null;
}

export interface WorkerStatus {
  status: 'ok' | 'stale' | 'missing' | 'unknown';
  last_seen_at: string | null;
  seconds_ago: number | null;
}

export interface HealthResponse {
  status: 'ok' | 'degraded';
  server_time: string;
  checks: Record<string, DependencyStatus>;
  workers?: Record<string, WorkerStatus>;
}

export const healthKeys = { ready: ['health', 'ready'] as const };

/**
 * `/health/ready` returns 503 with a valid body when degraded, so we read
 * the body ourselves instead of treating 503 as an error.
 */
export async function fetchReadiness(): Promise<HealthResponse> {
  const res = await fetch('/health/ready', { headers: { Accept: 'application/json' } });
  if (res.status !== 200 && res.status !== 503) {
    throw new Error(`Health check failed: HTTP ${res.status}`);
  }
  return (await res.json()) as HealthResponse;
}

export function useReadiness() {
  return useQuery({
    queryKey: healthKeys.ready,
    queryFn: fetchReadiness,
    refetchInterval: 10_000,
  });
}

export { apiRequest };
