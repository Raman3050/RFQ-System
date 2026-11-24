import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { API_V1, apiRequest } from '@/api/client';

import type { Page, RfqCreateInput, RfqDetail, RfqListParams, RfqSummary, RfqWrite } from './types';

const BASE = `${API_V1}/rfqs`;

export const rfqKeys = {
  all: ['rfqs'] as const,
  lists: () => [...rfqKeys.all, 'list'] as const,
  list: (params: RfqListParams) => [...rfqKeys.lists(), params] as const,
  detail: (id: string) => [...rfqKeys.all, 'detail', id] as const,
};

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
    refetchInterval: 15_000, // live updates arrive over WebSockets in Phase 5
  });
}

export function useRfq(id: string | undefined) {
  return useQuery({
    queryKey: rfqKeys.detail(id ?? ''),
    queryFn: () => apiRequest<RfqDetail>(`${BASE}/${id}`),
    enabled: !!id,
    refetchInterval: 15_000,
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
