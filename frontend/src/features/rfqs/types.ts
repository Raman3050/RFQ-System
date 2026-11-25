export type RfqStatus = 'SCHEDULED' | 'ACTIVE' | 'CLOSED' | 'FORCE_CLOSED' | 'CANCELLED';
export type TriggerType = 'BID_RECEIVED' | 'ANY_RANK_CHANGE' | 'L1_RANK_CHANGE';
export type Currency = 'INR' | 'USD' | 'EUR' | 'GBP' | 'AED' | 'SGD';

export const CURRENCIES: Currency[] = ['INR', 'USD', 'EUR', 'GBP', 'AED', 'SGD'];

export interface AuctionConfig {
  trigger_window_minutes: number;
  extension_minutes: number;
  trigger_type: TriggerType;
}

export interface RfqSummary {
  id: string;
  reference_id: string;
  name: string;
  buyer_company: string;
  status: RfqStatus;
  is_british_auction: boolean;
  currency: Currency;
  current_lowest_bid: string | null;
  bid_start_at: string;
  bid_close_at: string;
  current_close_at: string;
  forced_close_at: string;
  extension_count: number;
  invited_count: number;
}

export interface Invitation {
  email: string;
  status: 'JOINED' | 'PENDING_ACCOUNT';
  supplier_name: string | null;
  supplier_company: string | null;
  invited_at: string;
  last_notified_at: string | null;
  has_bid: boolean;
  can_remove: boolean;
}

export interface RfqDetail extends RfqSummary {
  pickup_date: string;
  auction_config: AuctionConfig | null;
  buyer: { full_name: string; company_name: string };
  version: number;
  closed_at: string | null;
  created_at: string;
  updated_at: string;
  invitations: Invitation[] | null;
  permissions: { can_edit: boolean; can_cancel: boolean; can_invite: boolean };
  server_time: string;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
  server_time: string;
}

export interface RfqWrite {
  name: string;
  bid_start_at: string;
  bid_close_at: string;
  forced_close_at: string;
  pickup_date: string;
  currency: Currency;
  is_british_auction: boolean;
  auction_config: AuctionConfig | null;
}

export interface RfqCreateInput extends RfqWrite {
  supplier_emails: string[];
}

export type RfqSort = 'created_desc' | 'close_asc' | 'start_asc' | 'start_desc';

export interface RfqListParams {
  status?: RfqStatus[];
  q?: string;
  sort?: RfqSort;
  page?: number;
  size?: number;
}

export const STATUS_LABEL: Record<RfqStatus, string> = {
  SCHEDULED: 'Upcoming',
  ACTIVE: 'Active',
  CLOSED: 'Closed',
  FORCE_CLOSED: 'Force closed',
  CANCELLED: 'Cancelled',
};

export const TRIGGER_LABEL: Record<TriggerType, { title: string; description: string }> = {
  BID_RECEIVED: {
    title: 'Any bid received',
    description: 'Extend whenever any supplier submits a bid in the last X minutes.',
  },
  ANY_RANK_CHANGE: {
    title: 'Any rank change',
    description: 'Extend when any supplier’s ranking changes in the last X minutes.',
  },
  L1_RANK_CHANGE: {
    title: 'Lowest bidder (L1) changes',
    description: 'Extend only when a different supplier becomes L1 in the last X minutes.',
  },
};

// ------------------------------------------------------------------ bidding

export interface BidInput {
  carrier_name: string;
  freight_charges: string;
  origin_charges: string;
  destination_charges: string;
  transit_time_days: number;
  quote_validity_until: string;
}

export interface Bid extends BidInput {
  id: string;
  total_amount: string;
  created_at: string;
}

export interface BidResult {
  bid: Bid;
  rank: number;
  total_bidders: number;
  current_close_at: string;
  extension: {
    previous_close_at: string;
    new_close_at: string;
    reason: string;
    capped: boolean;
  } | null;
  replayed: boolean;
  server_time: string;
}

export interface LeaderboardEntry {
  rank: number;
  label: string;
  supplier_label: string;
  is_you: boolean;
  total_amount: string;
  transit_time_days: number;
  bid_count: number;
  last_bid_at: string;
  supplier_name: string | null;
  carrier_name: string | null;
  freight_charges: string | null;
  origin_charges: string | null;
  destination_charges: string | null;
  quote_validity_until: string | null;
}

export interface Leaderboard {
  status: RfqStatus;
  currency: Currency;
  current_close_at: string;
  forced_close_at: string;
  extension_count: number;
  entries: LeaderboardEntry[];
  my_rank: number | null;
  my_current_total: string | null;
  server_time: string;
}

export interface AuctionEvent {
  id: number;
  type: string;
  created_at: string;
  actor: string | null;
  payload: Record<string, unknown>;
}

export interface EventPage {
  items: AuctionEvent[];
  next_before_id: number | null;
  server_time: string;
}
