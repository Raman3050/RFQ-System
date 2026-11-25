import type { Leaderboard, LeaderboardEntry, RfqDetail, RfqSummary } from '@/features/rfqs/types';

const HOUR = 3600_000;

export function makeRfq(overrides: Partial<RfqSummary> = {}): RfqSummary {
  const now = Date.now();
  return {
    id: 'rfq-1',
    reference_id: 'RFQ-2026-000001',
    name: 'Mumbai → Delhi FTL',
    buyer_company: 'Acme Manufacturing',
    status: 'SCHEDULED',
    is_british_auction: true,
    currency: 'INR',
    current_lowest_bid: null,
    bid_start_at: new Date(now - 10 * 60_000).toISOString(),
    bid_close_at: new Date(now + HOUR).toISOString(),
    current_close_at: new Date(now + HOUR).toISOString(),
    forced_close_at: new Date(now + 2 * HOUR).toISOString(),
    extension_count: 0,
    invited_count: 2,
    ...overrides,
  };
}

export function makeRfqDetail(overrides: Partial<RfqDetail> = {}): RfqDetail {
  return {
    ...makeRfq(),
    pickup_date: '2026-12-01',
    auction_config: {
      trigger_window_minutes: 10,
      extension_minutes: 5,
      trigger_type: 'BID_RECEIVED',
    },
    buyer: { full_name: 'Priya Sharma', company_name: 'Acme Manufacturing' },
    version: 1,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    invitations: [
      {
        email: 'supplier1@example.com',
        status: 'JOINED',
        supplier_name: 'Arjun Mehta',
        supplier_company: 'BlueDart Freight',
        invited_at: new Date().toISOString(),
        last_notified_at: new Date().toISOString(),
        has_bid: false,
        can_remove: true,
      },
      {
        email: 'new@example.com',
        status: 'PENDING_ACCOUNT',
        supplier_name: null,
        supplier_company: null,
        invited_at: new Date().toISOString(),
        last_notified_at: new Date().toISOString(),
        has_bid: false,
        can_remove: true,
      },
    ],
    permissions: { can_edit: true, can_cancel: true, can_invite: true },
    server_time: new Date().toISOString(),
    ...overrides,
  };
}

export function page<T>(items: T[]) {
  return { items, total: items.length, page: 1, size: 20, server_time: new Date().toISOString() };
}

export function entry(overrides: Partial<LeaderboardEntry> = {}): LeaderboardEntry {
  return {
    rank: 1,
    label: 'L1',
    supplier_label: 'BlueDart Freight',
    is_you: false,
    total_amount: '1000.00',
    transit_time_days: 3,
    bid_count: 1,
    last_bid_at: new Date().toISOString(),
    supplier_name: 'Arjun Mehta',
    carrier_name: 'BlueDart',
    freight_charges: '800.00',
    origin_charges: '100.00',
    destination_charges: '100.00',
    quote_validity_until: '2026-12-31',
    ...overrides,
  };
}

export function board(
  entries: LeaderboardEntry[],
  overrides: Partial<Leaderboard> = {},
): Leaderboard {
  const mine = entries.find((e) => e.is_you);
  return {
    status: 'ACTIVE',
    currency: 'INR',
    current_close_at: new Date(Date.now() + 3600_000).toISOString(),
    forced_close_at: new Date(Date.now() + 7200_000).toISOString(),
    extension_count: 0,
    entries,
    my_rank: mine?.rank ?? null,
    my_current_total: mine?.total_amount ?? null,
    server_time: new Date().toISOString(),
    ...overrides,
  };
}

export const noEvents = { items: [], next_before_id: null, server_time: new Date().toISOString() };
