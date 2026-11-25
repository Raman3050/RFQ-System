import { act, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { resetSession } from '@/features/auth/session';
import { FakeWebSocket } from '@/test/fakeWebSocket';
import { board, entry, makeRfq, makeRfqDetail, noEvents, page } from '@/test/fixtures';
import { authResponse, json, makeUser, mockApi } from '@/test/mockApi';
import { renderApp } from '@/test/render';

const asBuyer = {
  'POST /api/v1/auth/refresh': () => json(authResponse(makeUser('BUYER'), 'buyer-token')),
};

/** Mutable "server" state: live messages are followed by refetches that must agree. */
const server = { detail: makeRfqDetail({ current_lowest_bid: '1000.00' }) };

function detailRoutes(leaderboardCalls: { n: number }) {
  server.detail = makeRfqDetail({ current_lowest_bid: '1000.00' });
  return {
    ...asBuyer,
    'GET /api/v1/rfqs/rfq-1': () => json(server.detail),
    'GET /api/v1/rfqs/rfq-1/leaderboard': () => {
      leaderboardCalls.n += 1;
      return json(board([entry()]));
    },
    'GET /api/v1/rfqs/rfq-1/events?*': () => json(noEvents),
  };
}

async function goLive(): Promise<FakeWebSocket> {
  const ws = await waitFor(() => FakeWebSocket.latest());
  act(() => ws.open());
  expect(ws.sent[0]).toEqual({ type: 'auth', token: 'buyer-token' });
  act(() => ws.serverSend({ type: 'READY', server_time: new Date().toISOString() }));
  return ws;
}

const auction = (overrides = {}) => ({
  status: 'ACTIVE',
  bid_start_at: new Date(Date.now() - 600_000).toISOString(),
  current_close_at: new Date(Date.now() + 3600_000).toISOString(),
  forced_close_at: new Date(Date.now() + 7200_000).toISOString(),
  extension_count: 0,
  current_lowest_bid: '1000.00',
  ...overrides,
});

describe('live auction updates', () => {
  beforeEach(() => resetSession());

  it('authenticates over the socket, subscribes, and shows Live', async () => {
    mockApi(detailRoutes({ n: 0 }));
    renderApp('/auctions/rfq-1');
    await screen.findByRole('heading', { name: 'Mumbai → Delhi FTL' });

    const ws = await goLive();

    expect(ws.url).toMatch(/\/ws$/);
    expect(ws.sent).toContainEqual({ type: 'subscribe', rfq_ids: ['rfq-1'] });
    expect(await screen.findByRole('status', { name: 'Connection: Live' })).toBeInTheDocument();
  });

  it('applies an extension instantly, toasts it, and refetches the leaderboard', async () => {
    const calls = { n: 0 };
    mockApi(detailRoutes(calls));
    renderApp('/auctions/rfq-1');
    await screen.findByRole('heading', { name: 'Mumbai → Delhi FTL' });
    const ws = await goLive();
    const before = calls.n;

    const newClose = new Date(Date.now() + 2 * 3600_000).toISOString();
    server.detail = { ...server.detail, current_close_at: newClose, extension_count: 1 };
    act(() =>
      ws.serverSend({
        type: 'TIME_EXTENDED',
        rfq_id: 'rfq-1',
        seq: 42,
        server_time: new Date().toISOString(),
        auction: auction({
          current_close_at: newClose,
          extension_count: 1,
          current_lowest_bid: '900.00',
        }),
        extension: {
          previous_close_at: new Date().toISOString(),
          new_close_at: newClose,
          reason: 'Bid received in the last 10 minutes',
          capped: false,
        },
      }),
    );

    const toast = await screen.findByRole('alert');
    expect(within(toast).getByText(/Auction extended to/)).toBeInTheDocument();
    expect(within(toast).getByText(/bid received in the last 10 minutes/)).toBeInTheDocument();
    expect(
      await screen.findByText('CURRENT BID CLOSE (EXTENDED)', { exact: false }),
    ).toBeInTheDocument();
    await waitFor(() => expect(calls.n).toBeGreaterThan(before));
  });

  it('ignores messages for RFQs the page did not subscribe to', async () => {
    const calls = { n: 0 };
    mockApi(detailRoutes(calls));
    renderApp('/auctions/rfq-1');
    await screen.findByRole('heading', { name: 'Mumbai → Delhi FTL' });
    const ws = await goLive();
    const before = calls.n;

    act(() =>
      ws.serverSend({ type: 'BID_SUBMITTED', rfq_id: 'other', seq: 5, auction: auction() }),
    );
    await new Promise((r) => setTimeout(r, 50));
    expect(calls.n).toBe(before);
  });

  it('updates list rows live', async () => {
    let l1 = '1000.00';
    mockApi({
      ...asBuyer,
      'GET /api/v1/rfqs?*': () => json(page([makeRfq({ current_lowest_bid: l1 })])),
    });
    renderApp('/auctions');
    await screen.findByText('RFQ-2026-000001');
    const ws = await goLive();
    expect(ws.sent).toContainEqual({ type: 'subscribe', rfq_ids: ['rfq-1'] });

    l1 = '875.50';
    act(() =>
      ws.serverSend({
        type: 'BID_SUBMITTED',
        rfq_id: 'rfq-1',
        seq: 7,
        auction: auction({ current_lowest_bid: '875.50' }),
      }),
    );
    expect(await screen.findByText(/875\.50/)).toBeInTheDocument();
  });

  it('refreshes the session and reconnects when the token expires (4401)', async () => {
    let refreshes = 0;
    mockApi({
      ...detailRoutes({ n: 0 }),
      'POST /api/v1/auth/refresh': () => {
        refreshes += 1;
        return json(authResponse(makeUser('BUYER'), `token-${refreshes}`));
      },
    });
    renderApp('/auctions/rfq-1');
    await screen.findByRole('heading', { name: 'Mumbai → Delhi FTL' });
    const first = await waitFor(() => FakeWebSocket.latest());
    act(() => first.open());
    const beforeRefreshes = refreshes;

    act(() => first.close(4401));

    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(2));
    expect(refreshes).toBeGreaterThan(beforeRefreshes);
    const second = FakeWebSocket.latest();
    act(() => second.open());
    expect(second.sent[0]).toEqual({ type: 'auth', token: `token-${refreshes}` });
  });
});
