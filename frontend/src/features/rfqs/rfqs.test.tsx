import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';

import { resetSession } from '@/features/auth/session';
import { toLocalInput } from '@/lib/datetime';
import { makeRfq, makeRfqDetail, page } from '@/test/fixtures';
import { authResponse, json, makeUser, mockApi, problem } from '@/test/mockApi';
import { renderApp } from '@/test/render';

import { auctionPreview, defaultFormValues, rfqFormSchema, toWrite } from './form/schema';
import { liveStatus } from './status';

const HOUR = 3600_000;
const asBuyer = { 'POST /api/v1/auth/refresh': () => json(authResponse(makeUser('BUYER'))) };
const asSupplier = { 'POST /api/v1/auth/refresh': () => json(authResponse(makeUser('SUPPLIER'))) };

function bodyOf(fetchMock: ReturnType<typeof mockApi>, method: string, url: string) {
  const call = fetchMock.mock.calls.find(
    ([u, init]) => u === url && (init?.method ?? 'GET') === method,
  );
  return call ? JSON.parse(String(call[1]?.body)) : undefined;
}

// ------------------------------------------------------------------ pure logic

describe('liveStatus', () => {
  const now = Date.now();
  it('derives status from the clock', () => {
    const rfq = makeRfq({
      bid_start_at: new Date(now + HOUR).toISOString(),
      current_close_at: new Date(now + 2 * HOUR).toISOString(),
      forced_close_at: new Date(now + 3 * HOUR).toISOString(),
    });
    expect(liveStatus(rfq, now)).toBe('SCHEDULED');
    expect(liveStatus(rfq, now + HOUR)).toBe('ACTIVE');
    expect(liveStatus(rfq, now + 2 * HOUR)).toBe('CLOSED');
  });

  it('reports FORCE_CLOSED when the close reached the cap', () => {
    const t = new Date(now - 1000).toISOString();
    expect(liveStatus(makeRfq({ current_close_at: t, forced_close_at: t }), now)).toBe(
      'FORCE_CLOSED',
    );
  });

  it('keeps terminal statuses', () => {
    expect(liveStatus(makeRfq({ status: 'CANCELLED' }), now)).toBe('CANCELLED');
  });
});

describe('rfq form schema', () => {
  const schema = rfqFormSchema({ mode: 'create' });
  const base = defaultFormValues();

  const errorsFor = (patch: Partial<typeof base>) => {
    const r = schema.safeParse({ ...base, ...patch });
    return r.success ? {} : Object.fromEntries(r.error.issues.map((i) => [i.path[0], i.message]));
  };

  it('accepts the defaults', () => {
    expect(errorsFor({ name: 'Valid RFQ' })).toEqual({});
  });

  it('requires forced close strictly after bid close', () => {
    expect(errorsFor({ name: 'x RFQ', forced_close_at: base.bid_close_at })).toMatchObject({
      forced_close_at: 'Must be later than the bid close time',
    });
  });

  it('rejects a start in the past', () => {
    const past = toLocalInput(new Date(Date.now() - HOUR));
    expect(errorsFor({ name: 'x RFQ', bid_start_at: past })).toMatchObject({
      bid_start_at: 'Must be in the future',
    });
  });

  it('allows an unchanged past start when editing', () => {
    const past = toLocalInput(new Date(Date.now() - HOUR));
    const edit = rfqFormSchema({ mode: 'edit', originalStart: past });
    const r = edit.safeParse({ ...base, name: 'x RFQ', bid_start_at: past });
    expect(r.success).toBe(true);
  });

  it('validates X/Y minutes', () => {
    expect(errorsFor({ name: 'x RFQ', trigger_window_minutes: '0' })).toHaveProperty(
      'trigger_window_minutes',
    );
  });

  it('converts to the API shape (UTC ISO, null config when not British)', () => {
    const w = toWrite({ ...base, name: ' Trim me ', is_british_auction: false });
    expect(w.name).toBe('Trim me');
    expect(w.auction_config).toBeNull();
    expect(w.bid_start_at).toMatch(/Z$/);
    expect(Date.parse(w.bid_start_at)).toBe(Date.parse(base.bid_start_at));
  });

  it('previews the extension budget', () => {
    // defaults: 60 min bidding, 30 min buffer, Y = 5 → up to 6 extensions
    expect(auctionPreview(base)).toEqual({
      biddingMinutes: 60,
      bufferMinutes: 30,
      maxExtensions: 6,
    });
  });
});

// ------------------------------------------------------------------ pages

describe('auction listing', () => {
  beforeEach(() => resetSession());

  it('shows the spec columns with live status and countdown', async () => {
    mockApi({
      ...asBuyer,
      'GET /api/v1/rfqs?*': () =>
        json(
          page([
            makeRfq(),
            makeRfq({
              id: 'rfq-2',
              reference_id: 'RFQ-2026-000002',
              name: 'Chennai reefer',
              bid_start_at: new Date(Date.now() + 2 * HOUR).toISOString(),
              current_close_at: new Date(Date.now() + 3 * HOUR).toISOString(),
              forced_close_at: new Date(Date.now() + 4 * HOUR).toISOString(),
            }),
          ]),
        ),
    });
    renderApp('/auctions');

    const table = await screen.findByRole('table', { name: 'Auctions' });
    for (const header of [
      'RFQ',
      'Current lowest bid',
      'Current bid close',
      'Forced close',
      'Status',
    ]) {
      expect(within(table).getByRole('columnheader', { name: header })).toBeInTheDocument();
    }
    await within(table).findByText('RFQ-2026-000002');
    const rows = within(table).getAllByRole('row');
    expect(rows).toHaveLength(3);
    expect(within(rows[1]!).getByText('RFQ-2026-000001')).toBeInTheDocument();
    expect(within(rows[1]!).getByText('Active')).toBeInTheDocument();
    expect(within(rows[1]!).getByText(/Closes in/)).toBeInTheDocument();
    expect(within(rows[2]!).getByText('Upcoming')).toBeInTheDocument();
    expect(within(rows[2]!).getByText(/Starts in/)).toBeInTheDocument();
  });

  it('filters by status via the API', async () => {
    const fetchMock = mockApi({ ...asBuyer, 'GET /api/v1/rfqs?*': () => json(page([])) });
    const user = userEvent.setup();
    renderApp('/auctions');

    await user.click(await screen.findByRole('button', { name: 'Ended' }));

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([u]) => String(u).includes('status=CLOSED&status=FORCE_CLOSED')),
      ).toBe(true),
    );
  });
});

describe('create RFQ', () => {
  beforeEach(() => resetSession());

  it('submits the form as UTC ISO with auction config and invites', async () => {
    const created = makeRfqDetail({ id: 'new-rfq' });
    const fetchMock = mockApi({
      ...asBuyer,
      'POST /api/v1/rfqs': () => json(created, 201),
      'GET /api/v1/rfqs/new-rfq': () => json(created),
    });
    const user = userEvent.setup();
    renderApp('/rfqs/new');

    await user.type(await screen.findByLabelText('RFQ name'), 'Mumbai to Delhi FTL');
    await user.type(screen.getByLabelText('Supplier emails'), 'a@carrier.com, b@carrier.com,');
    await user.click(screen.getByRole('button', { name: 'Create RFQ' }));

    expect(await screen.findByText(/RFQ-2026-000001 created/)).toBeInTheDocument();
    const body = bodyOf(fetchMock, 'POST', '/api/v1/rfqs');
    expect(body).toMatchObject({
      name: 'Mumbai to Delhi FTL',
      is_british_auction: true,
      auction_config: {
        trigger_window_minutes: 10,
        extension_minutes: 5,
        trigger_type: 'BID_RECEIVED',
      },
      supplier_emails: ['a@carrier.com', 'b@carrier.com'],
    });
    expect(body.bid_start_at).toMatch(/Z$/);
  });

  it('blocks submit when forced close is not after close', async () => {
    const fetchMock = mockApi(asBuyer);
    const user = userEvent.setup();
    renderApp('/rfqs/new');

    await user.type(await screen.findByLabelText('RFQ name'), 'Bad schedule');
    const close = screen.getByLabelText('Bid close') as HTMLInputElement;
    const forced = screen.getByLabelText('Forced bid close');
    await user.clear(forced);
    await user.type(forced, close.value);
    await user.click(screen.getByRole('button', { name: 'Create RFQ' }));

    expect(await screen.findByText('Must be later than the bid close time')).toBeInTheDocument();
    expect(bodyOf(fetchMock, 'POST', '/api/v1/rfqs')).toBeUndefined();
  });

  it('shows server-side field errors next to the field', async () => {
    mockApi({
      ...asBuyer,
      'POST /api/v1/rfqs': () =>
        json(
          {
            type: 'about:blank',
            title: 'Unprocessable',
            status: 422,
            code: 'VALIDATION_ERROR',
            detail: 'Some emails cannot be invited',
            errors: [
              {
                loc: ['body', 'supplier_emails', 0],
                msg: 'buyer@x.com belongs to a buyer account and cannot be invited as a supplier',
                type: 'invitee_not_supplier',
              },
            ],
          },
          422,
        ),
    });
    const user = userEvent.setup();
    renderApp('/rfqs/new');

    await user.type(await screen.findByLabelText('RFQ name'), 'Mumbai to Delhi');
    await user.type(screen.getByLabelText('Supplier emails'), 'buyer@x.com,');
    await user.click(screen.getByRole('button', { name: 'Create RFQ' }));

    expect(await screen.findByText(/belongs to a buyer account/)).toBeInTheDocument();
  });
});

describe('RFQ details', () => {
  beforeEach(() => resetSession());

  it('shows schedule, auction rules and invitations to the buyer', async () => {
    mockApi({ ...asBuyer, 'GET /api/v1/rfqs/rfq-1': () => json(makeRfqDetail()) });
    renderApp('/auctions/rfq-1');

    expect(await screen.findByRole('heading', { name: 'Mumbai → Delhi FTL' })).toBeInTheDocument();
    expect(screen.getByText('Trigger window (X)')).toBeInTheDocument();
    expect(screen.getByText('10 min')).toBeInTheDocument();
    expect(screen.getByText('Any bid received')).toBeInTheDocument();
    expect(screen.getByText('BlueDart Freight')).toBeInTheDocument();
    expect(screen.getByText('Awaiting sign-up')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Edit' })).toBeInTheDocument();
  });

  it('hides buyer controls from suppliers', async () => {
    mockApi({
      ...asSupplier,
      'GET /api/v1/rfqs/rfq-1': () =>
        json(
          makeRfqDetail({
            invitations: null,
            permissions: { can_edit: false, can_cancel: false, can_invite: false },
          }),
        ),
    });
    renderApp('/auctions/rfq-1');

    expect(await screen.findByRole('heading', { name: 'Mumbai → Delhi FTL' })).toBeInTheDocument();
    expect(screen.queryByText('Invited suppliers')).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Edit' })).not.toBeInTheDocument();
  });

  it('shows a friendly message for an RFQ the user cannot see', async () => {
    mockApi({ ...asSupplier, 'GET /api/v1/rfqs/nope': () => problem(404, 'RFQ_NOT_FOUND') });
    renderApp('/auctions/nope');
    expect(await screen.findByText(/does not exist or you do not have access/)).toBeInTheDocument();
  });
});

describe('accept supplier invite', () => {
  beforeEach(() => resetSession());
  const TOKEN = 't'.repeat(40);
  const anon = { 'POST /api/v1/auth/refresh': () => problem(401, 'REFRESH_TOKEN_MISSING') };

  it('creates the supplier account from the link', async () => {
    const fetchMock = mockApi({
      ...anon,
      'POST /api/v1/auth/invitations/inspect': () =>
        json({
          email: 'new@carrier.com',
          invited_by_company: 'Acme Manufacturing',
          expires_at: new Date(Date.now() + 86_400_000).toISOString(),
        }),
      'POST /api/v1/auth/invitations/accept': () =>
        json(authResponse(makeUser('SUPPLIER', { email: 'new@carrier.com' })), 201),
      'GET /api/v1/rfqs?*': () => json(page([])),
    });
    const user = userEvent.setup();
    renderApp(`/accept-invite?token=${TOKEN}`);

    expect(await screen.findByDisplayValue('new@carrier.com')).toBeDisabled();
    expect(screen.getByText(/Acme Manufacturing invited you/)).toBeInTheDocument();
    await user.type(screen.getByLabelText('Full name'), 'Arjun Mehta');
    await user.type(screen.getByLabelText('Company (carrier)'), 'BlueDart');
    await user.type(screen.getByLabelText('Choose a password'), 'Carrier123');
    await user.click(screen.getByRole('button', { name: 'Create supplier account' }));

    expect(await screen.findByText('RFQs you have been invited to quote on')).toBeInTheDocument();
    expect(bodyOf(fetchMock, 'POST', '/api/v1/auth/invitations/accept')).toEqual({
      token: TOKEN,
      full_name: 'Arjun Mehta',
      company_name: 'BlueDart',
      password: 'Carrier123',
    });
  });

  it('explains an expired link', async () => {
    mockApi({
      ...anon,
      'POST /api/v1/auth/invitations/inspect': () =>
        problem(410, 'INVITE_EXPIRED', 'This invitation has expired. Ask the buyer to resend it.'),
    });
    renderApp(`/accept-invite?token=${TOKEN}`);
    expect(await screen.findByText(/has expired/)).toBeInTheDocument();
  });
});
