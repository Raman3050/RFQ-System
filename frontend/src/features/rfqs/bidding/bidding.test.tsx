import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';

import { resetSession } from '@/features/auth/session';
import { board, entry, makeRfqDetail, noEvents } from '@/test/fixtures';
import { authResponse, json, makeUser, mockApi, problem } from '@/test/mockApi';
import { renderApp } from '@/test/render';

const asBuyer = { 'POST /api/v1/auth/refresh': () => json(authResponse(makeUser('BUYER'))) };
const asSupplier = {
  'POST /api/v1/auth/refresh': () => json(authResponse(makeUser('SUPPLIER'))),
};
const supplierDetail = makeRfqDetail({
  invitations: null,
  permissions: { can_edit: false, can_cancel: false, can_invite: false },
  current_lowest_bid: '1000.00',
});

function callTo(fetchMock: ReturnType<typeof mockApi>, method: string, url: string) {
  return fetchMock.mock.calls.find(([u, init]) => u === url && (init?.method ?? 'GET') === method);
}

describe('leaderboard and activity log', () => {
  beforeEach(() => resetSession());

  it('shows the buyer every quote ranked with full details and extension reasons', async () => {
    mockApi({
      ...asBuyer,
      'GET /api/v1/rfqs/rfq-1': () => json(makeRfqDetail({ current_lowest_bid: '900.00' })),
      'GET /api/v1/rfqs/rfq-1/leaderboard': () =>
        json(
          board([
            entry({
              supplier_label: 'Swift Logistics',
              total_amount: '900.00',
              carrier_name: 'Swift',
            }),
            entry({ rank: 2, label: 'L2', total_amount: '1000.00' }),
          ]),
        ),
      'GET /api/v1/rfqs/rfq-1/events?*': () =>
        json({
          ...noEvents,
          items: [
            {
              id: 2,
              type: 'TIME_EXTENDED',
              created_at: new Date().toISOString(),
              actor: 'Swift Logistics',
              payload: {
                previous_close_at: '2026-11-24T18:00:00Z',
                new_close_at: '2026-11-24T18:05:00Z',
                reason: 'Bid received in the last 10 minutes',
                capped_at_forced_close: false,
              },
            },
            {
              id: 1,
              type: 'BID_SUBMITTED',
              created_at: new Date().toISOString(),
              actor: 'Swift Logistics',
              payload: {
                supplier_company: 'Swift Logistics',
                total_amount: '900.00',
                rank: 1,
                became_l1: true,
              },
            },
          ],
        }),
    });
    renderApp('/auctions/rfq-1');

    const table = await screen.findByRole('table', { name: 'Ranked bids' });
    const rows = within(table).getAllByRole('row');
    expect(within(rows[1]!).getByText('L1')).toBeInTheDocument();
    expect(within(rows[1]!).getByText('Swift Logistics')).toBeInTheDocument();
    expect(within(rows[2]!).getByText('L2')).toBeInTheDocument();
    expect(within(rows[2]!).getByText('BlueDart')).toBeInTheDocument(); // carrier visible to buyer

    const log = await screen.findByRole('list', { name: 'Activity log' });
    expect(
      within(log).getByText(/Reason: Bid received in the last 10 minutes/),
    ).toBeInTheDocument();
    expect(within(log).getByText(/new L1/)).toBeInTheDocument();
  });

  it('marks the supplier’s own row and hides competitor details', async () => {
    mockApi({
      ...asSupplier,
      'GET /api/v1/rfqs/rfq-1': () => json(supplierDetail),
      'GET /api/v1/rfqs/rfq-1/leaderboard': () =>
        json(
          board([
            entry({
              supplier_label: 'Bidder 1',
              supplier_name: null,
              carrier_name: null,
              freight_charges: null,
              origin_charges: null,
              destination_charges: null,
              quote_validity_until: null,
            }),
            entry({ rank: 2, label: 'L2', is_you: true, total_amount: '1200.00' }),
          ]),
        ),
      'GET /api/v1/rfqs/rfq-1/events?*': () => json(noEvents),
    });
    renderApp('/auctions/rfq-1');

    const table = await screen.findByRole('table', { name: 'Ranked bids' });
    expect(within(table).getByText('Bidder 1')).toBeInTheDocument();
    expect(within(table).getByText('You')).toBeInTheDocument();
    expect(screen.getByText(/Your rank:/)).toHaveTextContent('Your rank: L2 of 2');
    expect(screen.getByRole('heading', { name: 'Lower your bid' })).toBeInTheDocument();
  });
});

describe('bid form', () => {
  beforeEach(() => resetSession());

  it('submits a quote with an idempotency key and reports rank and extension', async () => {
    const fetchMock = mockApi({
      ...asSupplier,
      'GET /api/v1/rfqs/rfq-1': () => json(supplierDetail),
      'GET /api/v1/rfqs/rfq-1/leaderboard': () => json(board([entry()])),
      'GET /api/v1/rfqs/rfq-1/events?*': () => json(noEvents),
      'POST /api/v1/rfqs/rfq-1/bids': () =>
        json(
          {
            bid: { id: 'b1', total_amount: '950.00' },
            rank: 1,
            total_bidders: 2,
            current_close_at: '2026-11-24T18:05:00Z',
            extension: {
              previous_close_at: '2026-11-24T18:00:00Z',
              new_close_at: '2026-11-24T18:05:00Z',
              reason: 'Bid received in the last 10 minutes',
              capped: false,
            },
            replayed: false,
            server_time: new Date().toISOString(),
          },
          201,
        ),
    });
    const user = userEvent.setup();
    renderApp('/auctions/rfq-1');

    await user.type(await screen.findByLabelText('Freight charges'), '800');
    await user.clear(screen.getByLabelText('Origin charges'));
    await user.type(screen.getByLabelText('Origin charges'), '100.50');
    await user.clear(screen.getByLabelText('Destination charges'));
    await user.type(screen.getByLabelText('Destination charges'), '49.50');
    expect(screen.getByText('→ would be L1')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Submit bid' }));

    expect(await screen.findByText(/you are/)).toHaveTextContent('you are L1 of 2');
    expect(screen.getByText(/Auction extended to/)).toBeInTheDocument();

    const call = callTo(fetchMock, 'POST', '/api/v1/rfqs/rfq-1/bids');
    expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({
      freight_charges: '800',
      origin_charges: '100.50',
      destination_charges: '49.50',
      transit_time_days: 3,
    });
    expect((call?.[1]?.headers as Record<string, string>)['Idempotency-Key']).toBeTruthy();
  });

  it('requires a lower total than the supplier’s current bid', async () => {
    const fetchMock = mockApi({
      ...asSupplier,
      'GET /api/v1/rfqs/rfq-1': () => json(supplierDetail),
      'GET /api/v1/rfqs/rfq-1/leaderboard': () =>
        json(board([entry({ is_you: true, total_amount: '1000.00' })])),
      'GET /api/v1/rfqs/rfq-1/events?*': () => json(noEvents),
    });
    const user = userEvent.setup();
    renderApp('/auctions/rfq-1');

    await user.type(await screen.findByLabelText('Freight charges'), '1000');
    await user.click(screen.getByRole('button', { name: 'Submit lower bid' }));

    expect(
      await screen.findByText('Your new total must be lower than your current bid'),
    ).toBeInTheDocument();
    expect(callTo(fetchMock, 'POST', '/api/v1/rfqs/rfq-1/bids')).toBeUndefined();
  });

  it('requires the quote to stay valid until the pickup date', async () => {
    const fetchMock = mockApi({
      ...asSupplier,
      'GET /api/v1/rfqs/rfq-1': () => json({ ...supplierDetail, pickup_date: '2099-06-15' }),
      'GET /api/v1/rfqs/rfq-1/leaderboard': () => json(board([])),
      'GET /api/v1/rfqs/rfq-1/events?*': () => json(noEvents),
    });
    const user = userEvent.setup();
    renderApp('/auctions/rfq-1');

    const validity = await screen.findByLabelText('Quote valid until');
    expect(validity).toHaveValue('2099-06-15'); // default never lapses before pickup
    await user.clear(validity);
    await user.type(validity, '2099-06-14');
    await user.type(screen.getByLabelText('Freight charges'), '500');
    await user.click(screen.getByRole('button', { name: 'Submit bid' }));

    expect(
      await screen.findByText(/Must be valid at least until the pickup date/),
    ).toBeInTheDocument();
    expect(callTo(fetchMock, 'POST', '/api/v1/rfqs/rfq-1/bids')).toBeUndefined();
  });

  it('shows the server message when the auction has just closed', async () => {
    mockApi({
      ...asSupplier,
      'GET /api/v1/rfqs/rfq-1': () => json(supplierDetail),
      'GET /api/v1/rfqs/rfq-1/leaderboard': () => json(board([])),
      'GET /api/v1/rfqs/rfq-1/events?*': () => json(noEvents),
      'POST /api/v1/rfqs/rfq-1/bids': () =>
        problem(409, 'AUCTION_CLOSED', 'Bidding is closed for this auction'),
    });
    const user = userEvent.setup();
    renderApp('/auctions/rfq-1');

    await user.type(await screen.findByLabelText('Freight charges'), '500');
    await user.click(screen.getByRole('button', { name: 'Submit bid' }));
    expect(await screen.findByText('Bidding is closed for this auction')).toBeInTheDocument();
  });

  it('is not shown before bidding opens', async () => {
    const upcoming = {
      ...supplierDetail,
      bid_start_at: new Date(Date.now() + 3600_000).toISOString(),
      current_close_at: new Date(Date.now() + 7200_000).toISOString(),
      forced_close_at: new Date(Date.now() + 9000_000).toISOString(),
    };
    mockApi({
      ...asSupplier,
      'GET /api/v1/rfqs/rfq-1': () => json(upcoming),
      'GET /api/v1/rfqs/rfq-1/events?*': () => json(noEvents),
    });
    renderApp('/auctions/rfq-1');
    expect(await screen.findByText(/Bidding opens/)).toBeInTheDocument();
    expect(screen.queryByLabelText('Freight charges')).not.toBeInTheDocument();
  });
});

describe('removing invites', () => {
  beforeEach(() => resetSession());

  it('lets the buyer remove a supplier who has not bid', async () => {
    const detail = makeRfqDetail();
    const fetchMock = mockApi({
      ...asBuyer,
      'GET /api/v1/rfqs/rfq-1': () => json(detail),
      'GET /api/v1/rfqs/rfq-1/leaderboard': () => json(board([])),
      'GET /api/v1/rfqs/rfq-1/events?*': () => json(noEvents),
      'DELETE /api/v1/rfqs/rfq-1/invitations/new%40example.com': () =>
        json({ ...detail, invitations: detail.invitations!.slice(0, 1), invited_count: 1 }),
    });
    const user = userEvent.setup();
    renderApp('/auctions/rfq-1');

    await user.click(await screen.findByRole('button', { name: 'Remove new@example.com' }));
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Remove' }));

    await waitFor(() =>
      expect(
        callTo(fetchMock, 'DELETE', '/api/v1/rfqs/rfq-1/invitations/new%40example.com'),
      ).toBeDefined(),
    );
    expect(await screen.findByText('Removed new@example.com.')).toBeInTheDocument();
  });

  it('offers no remove button for suppliers who have bid', async () => {
    const detail = makeRfqDetail();
    detail.invitations = detail.invitations!.map((i) => ({
      ...i,
      has_bid: true,
      can_remove: false,
    }));
    mockApi({
      ...asBuyer,
      'GET /api/v1/rfqs/rfq-1': () => json(detail),
      'GET /api/v1/rfqs/rfq-1/leaderboard': () => json(board([])),
      'GET /api/v1/rfqs/rfq-1/events?*': () => json(noEvents),
    });
    renderApp('/auctions/rfq-1');

    expect(await screen.findAllByText('Has bid')).toHaveLength(2);
    expect(screen.queryByRole('button', { name: /^Remove / })).not.toBeInTheDocument();
  });
});
