import { z } from 'zod';

import { fromLocalInput, toLocalDate, toLocalInput } from '@/lib/datetime';

import type { RfqCreateInput, RfqDetail, RfqWrite } from '../types';

const MINUTES = z
  .string()
  .regex(/^\d+$/, 'Whole minutes only')
  .refine((v) => Number(v) >= 1 && Number(v) <= 1440, 'Between 1 and 1440 minutes');

const START_GRACE_MS = 60_000;
const MAX_SPAN_MS = 30 * 24 * 3600_000;

/**
 * Form schema. Mirrors backend rules (app/domain/rfq_rules.py) so users get instant
 * feedback; the server re-validates everything.
 */
export function rfqFormSchema(opts: { mode: 'create' | 'edit'; originalStart?: string }) {
  return z
    .object({
      name: z.string().trim().min(3, 'At least 3 characters').max(200),
      bid_start_at: z.string().min(1, 'Required'),
      bid_close_at: z.string().min(1, 'Required'),
      forced_close_at: z.string().min(1, 'Required'),
      pickup_date: z.string().min(1, 'Required'),
      currency: z.enum(['INR', 'USD', 'EUR', 'GBP', 'AED', 'SGD']),
      is_british_auction: z.boolean(),
      trigger_window_minutes: MINUTES,
      extension_minutes: MINUTES,
      trigger_type: z.enum(['BID_RECEIVED', 'ANY_RANK_CHANGE', 'L1_RANK_CHANGE']),
      supplier_emails: z.array(z.email('Invalid email address')).max(50, 'At most 50 at a time'),
    })
    .superRefine((v, ctx) => {
      const start = Date.parse(v.bid_start_at);
      const close = Date.parse(v.bid_close_at);
      const forced = Date.parse(v.forced_close_at);
      if ([start, close, forced].some(Number.isNaN)) return;

      const startChanged = opts.mode === 'create' || v.bid_start_at !== opts.originalStart;
      if (startChanged && start < Date.now() - START_GRACE_MS) {
        ctx.addIssue({ code: 'custom', path: ['bid_start_at'], message: 'Must be in the future' });
      }
      if (close <= start) {
        ctx.addIssue({
          code: 'custom',
          path: ['bid_close_at'],
          message: 'Must be after the bid start time',
        });
      }
      if (forced <= close) {
        ctx.addIssue({
          code: 'custom',
          path: ['forced_close_at'],
          message: 'Must be later than the bid close time',
        });
      } else if (forced - start > MAX_SPAN_MS) {
        ctx.addIssue({
          code: 'custom',
          path: ['forced_close_at'],
          message: 'At most 30 days after bid start',
        });
      }
      if (v.pickup_date && v.pickup_date < v.bid_start_at.slice(0, 10)) {
        ctx.addIssue({
          code: 'custom',
          path: ['pickup_date'],
          message: 'Cannot be before bidding starts',
        });
      }
    });
}

export type RfqFormValues = z.infer<ReturnType<typeof rfqFormSchema>>;

function roundUpToHour(d: Date): Date {
  const r = new Date(d);
  r.setMinutes(0, 0, 0);
  r.setHours(r.getHours() + 1);
  return r;
}

export function defaultFormValues(now = new Date()): RfqFormValues {
  const start = roundUpToHour(now);
  const close = new Date(start.getTime() + 60 * 60_000);
  const forced = new Date(close.getTime() + 30 * 60_000);
  const pickup = new Date(start.getTime() + 2 * 24 * 3600_000);
  return {
    name: '',
    bid_start_at: toLocalInput(start),
    bid_close_at: toLocalInput(close),
    forced_close_at: toLocalInput(forced),
    pickup_date: toLocalDate(pickup),
    currency: 'INR',
    is_british_auction: true,
    trigger_window_minutes: '10',
    extension_minutes: '5',
    trigger_type: 'BID_RECEIVED',
    supplier_emails: [],
  };
}

export function formValuesFromRfq(rfq: RfqDetail): RfqFormValues {
  return {
    name: rfq.name,
    bid_start_at: toLocalInput(rfq.bid_start_at),
    bid_close_at: toLocalInput(rfq.bid_close_at),
    forced_close_at: toLocalInput(rfq.forced_close_at),
    pickup_date: rfq.pickup_date,
    currency: rfq.currency,
    is_british_auction: rfq.is_british_auction,
    trigger_window_minutes: String(rfq.auction_config?.trigger_window_minutes ?? 10),
    extension_minutes: String(rfq.auction_config?.extension_minutes ?? 5),
    trigger_type: rfq.auction_config?.trigger_type ?? 'BID_RECEIVED',
    supplier_emails: [],
  };
}

export function toWrite(v: RfqFormValues): RfqWrite {
  return {
    name: v.name.trim(),
    bid_start_at: fromLocalInput(v.bid_start_at),
    bid_close_at: fromLocalInput(v.bid_close_at),
    forced_close_at: fromLocalInput(v.forced_close_at),
    pickup_date: v.pickup_date,
    currency: v.currency,
    is_british_auction: v.is_british_auction,
    auction_config: v.is_british_auction
      ? {
          trigger_window_minutes: Number(v.trigger_window_minutes),
          extension_minutes: Number(v.extension_minutes),
          trigger_type: v.trigger_type,
        }
      : null,
  };
}

export function toCreate(v: RfqFormValues): RfqCreateInput {
  return { ...toWrite(v), supplier_emails: v.supplier_emails };
}

/** How the configured auction can play out, for the live summary panel. */
export function auctionPreview(v: RfqFormValues): {
  biddingMinutes: number;
  bufferMinutes: number;
  maxExtensions: number;
} | null {
  const start = Date.parse(v.bid_start_at);
  const close = Date.parse(v.bid_close_at);
  const forced = Date.parse(v.forced_close_at);
  const y = Number(v.extension_minutes);
  if ([start, close, forced].some(Number.isNaN) || close <= start || forced <= close) return null;
  const bufferMinutes = Math.round((forced - close) / 60_000);
  return {
    biddingMinutes: Math.round((close - start) / 60_000),
    bufferMinutes,
    maxExtensions: y > 0 ? Math.ceil(bufferMinutes / y) : 0,
  };
}
