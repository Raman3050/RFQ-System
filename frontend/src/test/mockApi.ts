import { vi } from 'vitest';

import type { AuthResponse, Role, User } from '@/features/auth/types';

type Handler = (init: RequestInit | undefined) => Response | Promise<Response>;

export function json(body: unknown, status = 200): Response {
  const type = status >= 400 ? 'application/problem+json' : 'application/json';
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': type } });
}

export function problem(status: number, code: string, detail = code): Response {
  return json({ type: 'about:blank', title: 'Error', status, code, detail }, status);
}

export function makeUser(role: Role = 'BUYER', overrides: Partial<User> = {}): User {
  return {
    id: `user-${role.toLowerCase()}`,
    email: `${role.toLowerCase()}@example.com`,
    full_name: role === 'BUYER' ? 'Priya Sharma' : 'Arjun Mehta',
    company_name: role === 'BUYER' ? 'Acme Manufacturing' : 'BlueDart Freight',
    role,
    is_active: true,
    created_at: '2026-11-24T00:00:00Z',
    ...overrides,
  };
}

export function authResponse(user: User, token = 'access-1'): AuthResponse {
  return { access_token: token, token_type: 'bearer', expires_in: 900, user };
}

/**
 * Stubs global fetch with a route table keyed by "METHOD /path".
 * Unmatched requests fail the test loudly. Returns the mock for call assertions.
 */
export function mockApi(routes: Record<string, Handler>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString();
    const key = `${(init?.method ?? 'GET').toUpperCase()} ${url}`;
    const handler = routes[key];
    if (!handler) throw new Error(`Unmocked request: ${key}`);
    return handler(init);
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

export const ANON_REFRESH = {
  'POST /api/v1/auth/refresh': () => problem(401, 'REFRESH_TOKEN_MISSING'),
};
