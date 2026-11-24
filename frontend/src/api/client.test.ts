import { beforeEach, describe, expect, it, vi } from 'vitest';

import { getServerOffsetMs, resetServerTime } from '@/lib/serverTime';

import { ApiError, apiRequest } from './client';

function jsonResponse(body: unknown, status = 200, type = 'application/json'): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': type } });
}

describe('apiRequest', () => {
  beforeEach(() => resetServerTime());

  it('returns parsed JSON and sends JSON bodies', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ id: 1 }));
    vi.stubGlobal('fetch', fetchMock);

    const result = await apiRequest<{ id: number }>('/api/v1/x', {
      method: 'POST',
      json: { a: 1 },
    });

    expect(result).toEqual({ id: 1 });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.body).toBe('{"a":1}');
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json');
  });

  it('maps problem+json errors to ApiError with the domain code', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            type: 'about:blank',
            title: 'Conflict',
            status: 409,
            code: 'AUCTION_CLOSED',
            detail: 'Closed',
          },
          409,
          'application/problem+json',
        ),
      ),
    );

    const err = await apiRequest('/api/v1/x').catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 409, code: 'AUCTION_CLOSED', message: 'Closed' });
  });

  it('wraps network failures as NETWORK_ERROR', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    await expect(apiRequest('/api/v1/x')).rejects.toMatchObject({
      code: 'NETWORK_ERROR',
      status: 0,
    });
  });

  it('syncs the server clock offset from server_time', async () => {
    const serverTime = new Date(Date.now() + 60_000).toISOString();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ server_time: serverTime })));

    await apiRequest('/api/v1/x');

    expect(getServerOffsetMs()).toBeGreaterThan(55_000);
    expect(getServerOffsetMs()).toBeLessThan(65_000);
  });
});
