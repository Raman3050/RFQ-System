import { syncServerTime } from '@/lib/serverTime';

/** RFC 7807 problem+json body returned by the backend for every error. */
export interface ProblemDetails {
  type: string;
  title: string;
  status: number;
  code: string;
  detail: string;
  instance?: string;
  request_id?: string | null;
  errors?: { loc: (string | number)[]; msg: string; type: string }[];
  [key: string]: unknown;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly problem: ProblemDetails | null;

  constructor(
    status: number,
    code: string,
    message: string,
    problem: ProblemDetails | null,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.problem = problem;
  }
}

export const API_V1 = '/api/v1';

type RequestOptions = Omit<RequestInit, 'body'> & { json?: unknown };

/**
 * Thin fetch wrapper: JSON in/out, problem+json → ApiError, server-time sync.
 * Auth headers are added in Phase 1.
 */
export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { json, headers, ...rest } = options;
  const init: RequestInit = {
    ...rest,
    headers: {
      Accept: 'application/json',
      ...(json !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...headers,
    },
    body: json !== undefined ? JSON.stringify(json) : undefined,
  };

  let response: Response;
  try {
    response = await fetch(path, init);
  } catch (err) {
    throw new ApiError(0, 'NETWORK_ERROR', 'Unable to reach the server', null, { cause: err });
  }

  const contentType = response.headers.get('content-type') ?? '';
  const isJson = contentType.includes('json');
  const body: unknown = isJson ? await response.json().catch(() => null) : null;

  if (!response.ok) {
    const problem = isProblem(body) ? body : null;
    throw new ApiError(
      response.status,
      problem?.code ?? `HTTP_${response.status}`,
      problem?.detail ?? response.statusText,
      problem,
    );
  }

  if (body && typeof body === 'object' && 'server_time' in body) {
    syncServerTime(String((body as { server_time: unknown }).server_time));
  }
  return body as T;
}

function isProblem(body: unknown): body is ProblemDetails {
  return typeof body === 'object' && body !== null && 'code' in body && 'status' in body;
}
