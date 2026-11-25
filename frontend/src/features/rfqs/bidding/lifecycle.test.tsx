import { screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { resetSession } from '@/features/auth/session';
import { board, entry, makeRfqDetail, noEvents } from '@/test/fixtures';
import { authResponse, json, makeUser, mockApi } from '@/test/mockApi';
import { renderApp } from '@/test/render';

const ended = (overrides = {}) =>
  makeRfqDetail({
    bid_start_at: new Date(Date.now() - 3 * 3600_000).toISOString(),
    bid_close_at: new Date(Date.now() - 3600_000).toISOString(),
    current_close_at: new Date(Date.now() - 3600_000).toISOString(),
    forced_close_at: new Date(Date.now() + 3600_000).toISOString(),
    status: 'CLOSED',
    closed_at: new Date(Date.now() - 3590_000).toISOString(),
    extension_count: 2,
    ...overrides,
  });

const as = (role: 'BUYER' | 'SUPPLIER') => ({
  'POST /api/v1/auth/refresh': () => json(authResponse(makeUser(role))),
});

describe('auction result', () => {
  beforeEach(() => resetSession());

  it('shows the buyer the winner and logs the close', async () => {
    mockApi({
      ...as('BUYER'),
      'GET /api/v1/rfqs/rfq-1': () => json(ended()),
      'GET /api/v1/rfqs/rfq-1/leaderboard': () =>
        json(
          board(
            [
              entry({ supplier_label: 'Swift Logistics', total_amount: '35700.00' }),
              entry({ rank: 2, label: 'L2' }),
            ],
            { status: 'CLOSED' },
          ),
        ),
      'GET /api/v1/rfqs/rfq-1/events?*': () =>
        json({
          ...noEvents,
          items: [
            {
              id: 9,
              type: 'AUCTION_CLOSED',
              created_at: new Date().toISOString(),
              actor: null,
              payload: {
                reason: 'Bid close time reached',
                winning_supplier_company: 'Swift Logistics',
                winning_total: '35700.00',
                total_bids: 5,
                bidders: 2,
                extension_count: 2,
              },
            },
          ],
        }),
    });
    renderApp('/auctions/rfq-1');

    expect(await screen.findByText(/Winner: Swift Logistics at/)).toBeInTheDocument();
    expect(screen.getByText(/extended 2 times/)).toBeInTheDocument();
    const log = await screen.findByRole('list', { name: 'Activity log' });
    expect(within(log).getByText(/Auction closed/)).toBeInTheDocument();
    expect(within(log).getByText(/5 bids from 2 suppliers · 2 extensions/)).toBeInTheDocument();
  });

  it('tells a winning supplier they won', async () => {
    mockApi({
      ...as('SUPPLIER'),
      'GET /api/v1/rfqs/rfq-1': () => json(ended({ invitations: null })),
      'GET /api/v1/rfqs/rfq-1/leaderboard': () =>
        json(
          board([
            entry({ is_you: true }),
            entry({ rank: 2, label: 'L2', supplier_label: 'Bidder 2' }),
          ]),
        ),
      'GET /api/v1/rfqs/rfq-1/events?*': () => json(noEvents),
    });
    renderApp('/auctions/rfq-1');
    expect(await screen.findByText('You won this auction')).toBeInTheDocument();
    expect(screen.queryByLabelText('Freight charges')).not.toBeInTheDocument();
  });

  it('tells a losing supplier their final rank', async () => {
    mockApi({
      ...as('SUPPLIER'),
      'GET /api/v1/rfqs/rfq-1': () => json(ended({ invitations: null, status: 'FORCE_CLOSED' })),
      'GET /api/v1/rfqs/rfq-1/leaderboard': () =>
        json(
          board([
            entry({ supplier_label: 'Bidder 1' }),
            entry({ rank: 2, label: 'L2', is_you: true }),
          ]),
        ),
      'GET /api/v1/rfqs/rfq-1/events?*': () => json(noEvents),
    });
    renderApp('/auctions/rfq-1');
    expect(await screen.findByText('You finished L2 of 2')).toBeInTheDocument();
    expect(screen.getByText(/Force-closed at/)).toBeInTheDocument();
  });

  it('notes when the close has not been finalised yet', async () => {
    mockApi({
      ...as('BUYER'),
      'GET /api/v1/rfqs/rfq-1': () => json(ended({ status: 'CLOSED', closed_at: null })),
      'GET /api/v1/rfqs/rfq-1/leaderboard': () => json(board([], { status: 'CLOSED' })),
      'GET /api/v1/rfqs/rfq-1/events?*': () => json(noEvents),
    });
    renderApp('/auctions/rfq-1');
    expect(await screen.findByText('Auction ended with no bids')).toBeInTheDocument();
    expect(screen.getByText(/Finalising the result/)).toBeInTheDocument();
  });
});
