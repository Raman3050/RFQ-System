import type { RfqStatus, RfqSummary } from './types';

const TERMINAL: RfqStatus[] = ['CLOSED', 'FORCE_CLOSED', 'CANCELLED'];

/**
 * Client twin of the backend's effective_status: lets badges and countdowns flip
 * the moment a deadline passes, without waiting for the next refetch.
 */
export function liveStatus(rfq: RfqSummary, nowMs: number): RfqStatus {
  if (TERMINAL.includes(rfq.status)) return rfq.status;
  const start = Date.parse(rfq.bid_start_at);
  const close = Date.parse(rfq.current_close_at);
  const forced = Date.parse(rfq.forced_close_at);
  if (nowMs < start) return 'SCHEDULED';
  if (nowMs < close) return 'ACTIVE';
  return close >= forced ? 'FORCE_CLOSED' : 'CLOSED';
}
