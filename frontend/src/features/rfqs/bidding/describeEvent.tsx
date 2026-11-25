import Typography from '@mui/material/Typography';
import type { ReactNode } from 'react';

import { formatDateTime } from '@/lib/datetime';
import { formatMoney } from '@/lib/money';

import type { AuctionEvent, Currency } from '../types';

export type Tone = 'bid' | 'extension' | 'info' | 'warning';

export const DOT: Record<Tone, string> = {
  bid: 'primary.main',
  extension: 'warning.main',
  info: 'text.disabled',
  warning: 'error.main',
};

const str = (v: unknown) => (typeof v === 'string' ? v : '');

/** Turn an event into a sentence (and a tone for its marker). */
export function describeEvent(
  e: AuctionEvent,
  currency: Currency,
): { tone: Tone; text: ReactNode } {
  const p = e.payload;
  switch (e.type) {
    case 'BID_SUBMITTED': {
      const who = p.is_you ? 'You' : str(p.supplier_company) || e.actor || 'A supplier';
      const verb = p.is_revision ? 'lowered their bid to' : 'bid';
      return {
        tone: 'bid',
        text: (
          <>
            <b>{who}</b> {p.is_you ? verb.replace('their', 'your') : verb}{' '}
            <b>{formatMoney(str(p.total_amount), currency)}</b> → L{String(p.rank)}
            {p.became_l1 ? ' (new L1)' : ''}
          </>
        ),
      };
    }
    case 'TIME_EXTENDED':
      return {
        tone: 'extension',
        text: (
          <>
            <b>Auction extended</b> from {formatDateTime(str(p.previous_close_at))} to{' '}
            <b>{formatDateTime(str(p.new_close_at))}</b>
            <Typography
              variant="body2"
              color="text.secondary"
              component="span"
              sx={{ display: 'block' }}
            >
              Reason: {str(p.reason)}
              {p.capped_at_forced_close ? ' · limited by the forced close time' : ''}
            </Typography>
          </>
        ),
      };
    case 'RFQ_CREATED':
      return { tone: 'info', text: <>RFQ created by {e.actor}</> };
    case 'RFQ_UPDATED':
      return { tone: 'info', text: <>RFQ details updated</> };
    case 'RFQ_CANCELLED':
      return { tone: 'warning', text: <>RFQ cancelled</> };
    case 'SUPPLIER_INVITED':
      return {
        tone: 'info',
        text: (
          <>
            Invited {str(p.email)}
            {p.has_account ? '' : ' (sign-up link sent)'}
          </>
        ),
      };
    case 'SUPPLIER_JOINED':
      return { tone: 'info', text: <>{str(p.company)} joined as a supplier</> };
    case 'SUPPLIER_REMOVED':
      return { tone: 'warning', text: <>Removed invitation for {str(p.email)}</> };
    case 'AUCTION_CLOSED':
      return { tone: 'info', text: <>Auction closed</> };
    case 'AUCTION_FORCE_CLOSED':
      return { tone: 'warning', text: <>Auction force-closed</> };
    default:
      return { tone: 'info', text: e.type };
  }
}
