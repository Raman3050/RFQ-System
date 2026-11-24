import type { RfqDetail, RfqSummary } from '@/features/rfqs/types';

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
      },
      {
        email: 'new@example.com',
        status: 'PENDING_ACCOUNT',
        supplier_name: null,
        supplier_company: null,
        invited_at: new Date().toISOString(),
        last_notified_at: new Date().toISOString(),
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
