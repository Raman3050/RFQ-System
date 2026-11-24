import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { apiRequest, setAuthHandlers } from '@/api/client';
import { authResponse, json, makeUser, mockApi, problem } from '@/test/mockApi';

import * as session from './session';

describe('session', () => {
  beforeEach(() => session.resetSession());
  afterEach(() => setAuthHandlers(null));

  it('dedupes concurrent refreshes into one request', async () => {
    // Refresh tokens rotate: two parallel refreshes with the same cookie would
    // trip reuse detection on the server and kill the session.
    const fetchMock = mockApi({
      'POST /api/v1/auth/refresh': async () => {
        await new Promise((r) => setTimeout(r, 10));
        return json(authResponse(makeUser(), 'fresh'));
      },
    });

    const [a, b, c] = await Promise.all([session.refresh(), session.refresh(), session.refresh()]);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(a?.access_token).toBe('fresh');
    expect(b).toBe(a);
    expect(c).toBe(a);
    expect(session.getAccessToken()).toBe('fresh');
  });

  it('clears the session when refresh fails', async () => {
    mockApi({ 'POST /api/v1/auth/login': () => json(authResponse(makeUser(), 'old')) });
    await session.login({ email: 'buyer@example.com', password: 'x' });
    expect(session.getAccessToken()).toBe('old');

    mockApi({ 'POST /api/v1/auth/refresh': () => problem(401, 'REFRESH_TOKEN_REUSED') });
    expect(await session.refresh()).toBeNull();
    expect(session.getAccessToken()).toBeNull();
  });
});

describe('apiRequest auth handling', () => {
  beforeEach(() => session.resetSession());
  afterEach(() => setAuthHandlers(null));

  it('attaches the token, refreshes once on TOKEN_EXPIRED, and retries', async () => {
    let token = 'stale';
    setAuthHandlers({
      getAccessToken: () => token,
      refreshAccessToken: async () => {
        token = 'fresh';
        return token;
      },
    });
    const fetchMock = mockApi({
      'GET /api/v1/things': (init) => {
        const auth = (init?.headers as Record<string, string>).Authorization;
        return auth === 'Bearer fresh' ? json({ ok: true }) : problem(401, 'TOKEN_EXPIRED');
      },
    });

    await expect(apiRequest('/api/v1/things')).resolves.toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('gives up when the refresh fails', async () => {
    setAuthHandlers({ getAccessToken: () => 'stale', refreshAccessToken: async () => null });
    mockApi({ 'GET /api/v1/things': () => problem(401, 'TOKEN_EXPIRED') });

    await expect(apiRequest('/api/v1/things')).rejects.toMatchObject({ code: 'TOKEN_EXPIRED' });
  });

  it('does not refresh on 403', async () => {
    let refreshed = false;
    setAuthHandlers({
      getAccessToken: () => 't',
      refreshAccessToken: async () => {
        refreshed = true;
        return 't2';
      },
    });
    mockApi({ 'GET /api/v1/things': () => problem(403, 'FORBIDDEN_ROLE') });

    await expect(apiRequest('/api/v1/things')).rejects.toMatchObject({ status: 403 });
    expect(refreshed).toBe(false);
  });
});
