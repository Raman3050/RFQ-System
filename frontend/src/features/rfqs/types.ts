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
}

export interface RfqDetail extends RfqSummary {
  pickup_date: string;
  auction_config: AuctionConfig | null;
  buyer: { full_name: string; company_name: string };
  version: number;
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
