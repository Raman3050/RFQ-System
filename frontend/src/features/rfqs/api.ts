import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';

import { API_V1, apiRequest } from '@/api/client';
import { liveClient } from '@/features/realtime/liveClient';

import type {
  BidInput,
  BidResult,
  EventPage,
  Leaderboard,
  Page,
  RfqCreateInput,
  RfqDetail,
  RfqListParams,
  RfqStatus,
  RfqSummary,
  RfqWrite,
} from './types';

const BASE = `${API_V1}/rfqs`;

export const rfqKeys = {
  all: ['rfqs'] as const,
  lists: () => [...rfqKeys.all, 'list'] as const,
  list: (params: RfqListParams) => [...rfqKeys.lists(), params] as const,
  detail: (id: string) => [...rfqKeys.all, 'detail', id] as const,
  leaderboard: (id: string) => [...rfqKeys.all, 'leaderboard', id] as const,
  events: (id: string) => [...rfqKeys.all, 'events', id] as const,
};

/**
 * With a live WebSocket, pushes drive refetches and we only keep a slow safety refresh.
 * Without one (blocked by a proxy, reconnecting), fall back to polling.
 */
const SAFETY_REFRESH_MS = 60_000;
const pollFor = (status: RfqStatus | undefined) =>
  liveClient.isLive() ? SAFETY_REFRESH_MS : status === 'ACTIVE' ? 5_000 : 30_000;

function toQuery(params: RfqListParams): string {
  const qs = new URLSearchParams();
  params.status?.forEach((s) => qs.append('status', s));
  if (params.q?.trim()) qs.set('q', params.q.trim());
  if (params.sort) qs.set('sort', params.sort);
  if (params.page) qs.set('page', String(params.page));
  if (params.size) qs.set('size', String(params.size));
  const s = qs.toString();
  return s ? `?${s}` : '';
}

export function useRfqList(params: RfqListParams) {
  return useQuery({
    queryKey: rfqKeys.list(params),
    queryFn: () => apiRequest<Page<RfqSummary>>(`${BASE}${toQuery(params)}`),
    placeholderData: keepPreviousData,
    refetchInterval: () => (liveClient.isLive() ? SAFETY_REFRESH_MS : 15_000),
  });
}

export function useRfq(id: string | undefined) {
  return useQuery({
    queryKey: rfqKeys.detail(id ?? ''),
    queryFn: () => apiRequest<RfqDetail>(`${BASE}/${id}`),
    enabled: !!id,
    refetchInterval: (q) => pollFor(q.state.data?.status),
  });
}

function useRfqMutation<TVars>(fn: (vars: TVars) => Promise<RfqDetail>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (rfq) => {
      qc.setQueryData(rfqKeys.detail(rfq.id), rfq);
      void qc.invalidateQueries({ queryKey: rfqKeys.lists() });
    },
  });
}

export function useCreateRfq() {
  return useRfqMutation((input: RfqCreateInput) =>
    apiRequest<RfqDetail>(BASE, { method: 'POST', json: input }),
  );
}

export function useUpdateRfq(id: string) {
  return useRfqMutation(({ input, version }: { input: Partial<RfqWrite>; version: number }) =>
    apiRequest<RfqDetail>(`${BASE}/${id}`, {
      method: 'PATCH',
      json: input,
      headers: { 'If-Match': `"${version}"` },
    }),
  );
}

export function useCancelRfq(id: string) {
  return useRfqMutation((version: number) =>
    apiRequest<RfqDetail>(`${BASE}/${id}/cancel`, {
      method: 'POST',
      headers: { 'If-Match': `"${version}"` },
    }),
  );
}

export function useInviteSuppliers(id: string) {
  return useRfqMutation((emails: string[]) =>
    apiRequest<RfqDetail>(`${BASE}/${id}/invitations`, { method: 'POST', json: { emails } }),
  );
}

export function useResendInvitation(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (email: string) =>
      apiRequest<{ status: string }>(
        `${BASE}/${id}/invitations/${encodeURIComponent(email)}/resend`,
        { method: 'POST' },
      ),
    onSuccess: () => void qc.invalidateQueries({ queryKey: rfqKeys.detail(id) }),
  });
}

// ------------------------------------------------------------------ bidding

export function useLeaderboard(id: string, enabled = true) {
  return useQuery({
    queryKey: rfqKeys.leaderboard(id),
    queryFn: () => apiRequest<Leaderboard>(`${BASE}/${id}/leaderboard`),
    enabled: !!id && enabled,
    refetchInterval: (q) => pollFor(q.state.data?.status),
  });
}

export function useActivity(id: string, live: boolean) {
  return useInfiniteQuery({
    queryKey: rfqKeys.events(id),
    queryFn: ({ pageParam }) =>
      apiRequest<EventPage>(
        `${BASE}/${id}/events?limit=30${pageParam ? `&before_id=${pageParam}` : ''}`,
      ),
    initialPageParam: null as number | null,
    getNextPageParam: (last) => last.next_before_id,
    enabled: !!id,
    refetchInterval: () => (live && !liveClient.isLive() ? 5_000 : false),
  });
}

/** Invalidate everything a bid can change. */
function useInvalidateAuction(id: string) {
  const qc = useQueryClient();
  return () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: rfqKeys.detail(id) }),
      qc.invalidateQueries({ queryKey: rfqKeys.leaderboard(id) }),
      qc.invalidateQueries({ queryKey: rfqKeys.events(id) }),
      qc.invalidateQueries({ queryKey: rfqKeys.lists() }),
    ]);
}

export function useSubmitBid(id: string) {
  const invalidate = useInvalidateAuction(id);
  return useMutation({
    // One key per submit attempt: retries of the same attempt can't double-bid.
    mutationFn: ({ input, idempotencyKey }: { input: BidInput; idempotencyKey: string }) =>
      apiRequest<BidResult>(`${BASE}/${id}/bids`, {
        method: 'POST',
        json: input,
        headers: { 'Idempotency-Key': idempotencyKey },
      }),
    onSettled: () => void invalidate(),
  });
}

export function useRemoveInvitation(id: string) {
  const invalidate = useInvalidateAuction(id);
  return useRfqMutation((email: string) =>
    apiRequest<RfqDetail>(`${BASE}/${id}/invitations/${encodeURIComponent(email)}`, {
      method: 'DELETE',
    }).then((r) => {
      void invalidate();
      return r;
    }),
  );
}
