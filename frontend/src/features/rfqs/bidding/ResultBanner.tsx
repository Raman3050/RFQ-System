import Alert from '@mui/material/Alert';
import AlertTitle from '@mui/material/AlertTitle';

import { formatDateTime } from '@/lib/datetime';
import { formatMoney } from '@/lib/money';

import type { Leaderboard, RfqDetail, RfqStatus } from '../types';

/**
 * Final outcome of an ended auction. Shown from the moment the deadline passes
 * (status derived from the clock); "finalising" until the lifecycle worker has
 * persisted the close (closed_at set).
 */
export function ResultBanner({
  rfq,
  board,
  status,
  isSupplier,
}: {
  rfq: RfqDetail;
  board: Leaderboard | undefined;
  status: RfqStatus;
  isSupplier: boolean;
}) {
  if (status !== 'CLOSED' && status !== 'FORCE_CLOSED') return null;
  const forced = status === 'FORCE_CLOSED';
  const winner = board?.entries[0];
  const bidders = board?.entries.length ?? 0;
  const endedAt = formatDateTime(rfq.current_close_at);
  const how = forced
    ? `Force-closed at ${endedAt} — extensions reached the forced close time.`
    : `Closed at ${endedAt}.`;
  const finalising = !rfq.closed_at && ' Finalising the result…';

  if (!winner) {
    return (
      <Alert severity="info">
        <AlertTitle>Auction ended with no bids</AlertTitle>
        {how}
        {finalising}
      </Alert>
    );
  }

  const price = formatMoney(winner.total_amount, rfq.currency);

  if (isSupplier) {
    const mine = board?.entries.find((e) => e.is_you);
    if (!mine) {
      return (
        <Alert severity="info">
          <AlertTitle>Auction ended</AlertTitle>
          {how} You did not submit a quote. Winning price: {price}.{finalising}
        </Alert>
      );
    }
    return mine.rank === 1 ? (
      <Alert severity="success">
        <AlertTitle>You won this auction</AlertTitle>
        {how} Your quote of {price} finished L1 of {bidders}.{finalising}
      </Alert>
    ) : (
      <Alert severity="info">
        <AlertTitle>
          You finished {mine.label} of {bidders}
        </AlertTitle>
        {how} Your best quote: {formatMoney(mine.total_amount, rfq.currency)}. Winning price:{' '}
        {price}.{finalising}
      </Alert>
    );
  }

  return (
    <Alert severity="success">
      <AlertTitle>
        Winner: {winner.supplier_label} at {price}
      </AlertTitle>
      {how} {bidders} supplier{bidders === 1 ? '' : 's'} bid
      {rfq.extension_count > 0 &&
        `; the close was extended ${rfq.extension_count} time${rfq.extension_count === 1 ? '' : 's'}`}
      .{finalising}
    </Alert>
  );
}
