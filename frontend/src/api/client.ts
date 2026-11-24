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

// ------------------------------------------------------------------ auth integration

/**
 * The auth layer registers these so the client can attach the access token and
 * transparently recover from an expired one, without importing React state.
 */
export interface AuthHandlers {
  getAccessToken: () => string | null;
  /** Obtain a fresh access token (refresh-cookie rotation). Null = session is gone. */
  refreshAccessToken: () => Promise<string | null>;
}

let authHandlers: AuthHandlers | null = null;

export function setAuthHandlers(handlers: AuthHandlers | null): void {
  authHandlers = handlers;
}

/** 401 codes meaning "your access token is stale, a refresh may fix it". */
const REFRESHABLE_CODES = new Set(['TOKEN_EXPIRED', 'TOKEN_INVALID', 'NOT_AUTHENTICATED']);

// ------------------------------------------------------------------ request

export type RequestOptions = Omit<RequestInit, 'body'> & {
  json?: unknown;
  /** Attach the bearer token and retry once after a refresh. Default true. */
  auth?: boolean;
};

/** JSON in/out, problem+json → ApiError, bearer auth with one refresh-and-retry. */
export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { auth = true, ...rest } = options;
  try {
    return await send<T>(path, rest, auth ? authHandlers?.getAccessToken() : null);
  } catch (err) {
    if (
      auth &&
      authHandlers &&
      err instanceof ApiError &&
      err.status === 401 &&
      REFRESHABLE_CODES.has(err.code)
    ) {
      const fresh = await authHandlers.refreshAccessToken();
      if (fresh) return send<T>(path, rest, fresh);
    }
    throw err;
  }
}

async function send<T>(
  path: string,
  options: Omit<RequestOptions, 'auth'>,
  accessToken: string | null | undefined,
): Promise<T> {
  const { json, headers, ...rest } = options;
  const init: RequestInit = {
    credentials: 'same-origin',
    ...rest,
    headers: {
      Accept: 'application/json',
      ...(json !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
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

/** First field-level message for a form field from a 422 problem, if any. */
export function fieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError) || !error.problem?.errors) return {};
  const out: Record<string, string> = {};
  for (const e of error.problem.errors) {
    // ["body", "supplier_emails", 2] → the list field "supplier_emails".
    const field = [...e.loc].reverse().find((p): p is string => typeof p === 'string');
    if (field && field !== 'body' && !(field in out)) {
      out[field] = e.msg.replace(/^Value error, /, '');
    }
  }
  return out;
}
