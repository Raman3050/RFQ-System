/**
 * Session core (framework-free).
 *
 * - The access token lives only in memory (never localStorage) to limit XSS impact.
 * - The refresh token is an httpOnly cookie the browser sends to /api/v1/auth only.
 * - Refreshes are single-flight within a tab and serialised across tabs with the Web
 *   Locks API. Refresh tokens rotate and a replayed token revokes the whole session,
 *   so two tabs racing with the same cookie would log the user out.
 */
import { API_V1, apiRequest } from '@/api/client';

import type { AcceptInviteInput, AuthResponse, LoginInput, RegisterInput } from './types';

type Listener = (session: AuthResponse | null) => void;

let current: AuthResponse | null = null;
let inflight: Promise<AuthResponse | null> | null = null;
const listeners = new Set<Listener>();

function publish(session: AuthResponse | null): void {
  current = session;
  for (const l of listeners) l(session);
}

export function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getAccessToken(): string | null {
  return current?.access_token ?? null;
}

export async function login(input: LoginInput): Promise<AuthResponse> {
  const session = await apiRequest<AuthResponse>(`${API_V1}/auth/login`, {
    method: 'POST',
    json: input,
    auth: false,
  });
  publish(session);
  return session;
}

export async function register(input: RegisterInput): Promise<AuthResponse> {
  const session = await apiRequest<AuthResponse>(`${API_V1}/auth/register`, {
    method: 'POST',
    json: input,
    auth: false,
  });
  publish(session);
  return session;
}

/** Create a supplier account from an emailed invite link and start a session. */
export async function acceptInvite(input: AcceptInviteInput): Promise<AuthResponse> {
  const session = await apiRequest<AuthResponse>(`${API_V1}/auth/invitations/accept`, {
    method: 'POST',
    json: input,
    auth: false,
  });
  publish(session);
  return session;
}

export async function logout(): Promise<void> {
  try {
    await apiRequest<void>(`${API_V1}/auth/logout`, { method: 'POST', auth: false });
  } finally {
    publish(null);
  }
}

/** Rotate the refresh cookie. Resolves null (and clears the session) if it's gone. */
export function refresh(): Promise<AuthResponse | null> {
  inflight ??= withCrossTabLock(doRefresh).finally(() => {
    inflight = null;
  });
  return inflight;
}

async function doRefresh(): Promise<AuthResponse | null> {
  try {
    const session = await apiRequest<AuthResponse>(`${API_V1}/auth/refresh`, {
      method: 'POST',
      auth: false,
    });
    publish(session);
    return session;
  } catch {
    publish(null);
    return null;
  }
}

async function withCrossTabLock<T>(fn: () => Promise<T>): Promise<T> {
  const locks = typeof navigator !== 'undefined' ? navigator.locks : undefined;
  if (!locks) return fn();
  return locks.request('rfq-auth-refresh', fn);
}

/** Test helper. */
export function resetSession(): void {
  current = null;
  inflight = null;
  listeners.clear();
}
