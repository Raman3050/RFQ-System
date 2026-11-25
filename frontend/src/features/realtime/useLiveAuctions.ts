import { useQueryClient, type QueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useSyncExternalStore } from 'react';

import { rfqKeys } from '@/features/rfqs/api';
import type { Page, RfqDetail, RfqSummary } from '@/features/rfqs/types';

import { liveClient, type LiveMessage, type LiveState } from './liveClient';

/** Events after which the per-viewer views (leaderboard, activity, details) must refetch. */
const REFETCH_ON = new Set([
  'BID_SUBMITTED',
  'TIME_EXTENDED',
  'AUCTION_STARTED',
  'AUCTION_CLOSED',
  'AUCTION_FORCE_CLOSED',
  'RFQ_UPDATED',
  'RFQ_CANCELLED',
]);

/** Patch the public auction fields straight into cached detail + list data. */
function applyAuctionState(qc: QueryClient, msg: LiveMessage): void {
  const id = msg.rfq_id;
  const a = msg.auction;
  if (!id || !a) return;
  const patch = {
    status: a.status as RfqSummary['status'],
    bid_start_at: a.bid_start_at,
    current_close_at: a.current_close_at,
    forced_close_at: a.forced_close_at,
    extension_count: a.extension_count,
    current_lowest_bid: a.current_lowest_bid,
  };
  qc.setQueryData<RfqDetail>(rfqKeys.detail(id), (old) => (old ? { ...old, ...patch } : old));
  qc.setQueriesData<Page<RfqSummary>>({ queryKey: rfqKeys.lists() }, (old) =>
    old ? { ...old, items: old.items.map((r) => (r.id === id ? { ...r, ...patch } : r)) } : old,
  );
}

const lastSeq = new Map<string, number>();

function refetchViews(qc: QueryClient, id: string): void {
  void qc.invalidateQueries({ queryKey: rfqKeys.leaderboard(id) });
  void qc.invalidateQueries({ queryKey: rfqKeys.events(id) });
  void qc.invalidateQueries({ queryKey: rfqKeys.detail(id) });
}

/**
 * Subscribe the current page to live updates for these RFQs. Caches update instantly;
 * leaderboard/activity refetch so per-viewer visibility rules stay server-side.
 */
export function useLiveAuctions(ids: string[], onMessage?: (msg: LiveMessage) => void): LiveState {
  const qc = useQueryClient();
  const key = [...ids].sort().join(',');
  const onMessageRef = useRef(onMessage);
  useEffect(() => {
    onMessageRef.current = onMessage;
  });

  useEffect(() => {
    if (!key) return;
    const wanted = new Set(key.split(','));
    const off = liveClient.onMessage((msg) => {
      const id = msg.rfq_id;
      if (!id || !wanted.has(id)) return;
      applyAuctionState(qc, msg);
      const seq = msg.seq ?? 0;
      const known = lastSeq.get(id);
      if (msg.type === 'SNAPSHOT') {
        // Reconnected (or first load): if anything happened while we weren't listening,
        // our cached views are stale.
        if (known !== undefined && seq > known) refetchViews(qc, id);
      } else if (REFETCH_ON.has(msg.type)) {
        refetchViews(qc, id);
        void qc.invalidateQueries({ queryKey: rfqKeys.lists() });
      }
      if (known === undefined || seq > known) lastSeq.set(id, seq);
      onMessageRef.current?.(msg);
    });
    const release = liveClient.subscribe([...wanted]);
    return () => {
      off();
      release();
    };
  }, [key, qc]);

  return useLiveState();
}

export function useLiveState(): LiveState {
  return useSyncExternalStore((cb) => liveClient.onStateChange(cb), liveClient.getState);
}
