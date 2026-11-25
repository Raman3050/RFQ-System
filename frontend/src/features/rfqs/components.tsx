import Chip, { type ChipProps } from '@mui/material/Chip';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';

import { formatDuration } from '@/lib/datetime';
import { formatMoney } from '@/lib/money';
import { useNow } from '@/lib/useNow';

import { liveStatus } from './status';
import { STATUS_LABEL, type RfqStatus, type RfqSummary } from './types';

const STATUS_COLOR: Record<RfqStatus, ChipProps['color']> = {
  SCHEDULED: 'info',
  ACTIVE: 'success',
  CLOSED: 'default',
  FORCE_CLOSED: 'warning',
  CANCELLED: 'error',
};

export function StatusBadge({
  status,
  size = 'small',
}: {
  status: RfqStatus;
  size?: ChipProps['size'];
}) {
  return (
    <Chip
      label={STATUS_LABEL[status]}
      color={STATUS_COLOR[status]}
      size={size}
      variant={status === 'ACTIVE' ? 'filled' : 'outlined'}
      sx={{ fontWeight: 600 }}
    />
  );
}

/** Badge that updates itself when the start/close deadline passes. */
export function LiveStatusBadge({ rfq, size }: { rfq: RfqSummary; size?: ChipProps['size'] }) {
  const now = useNow();
  return <StatusBadge status={liveStatus(rfq, now)} size={size} />;
}

/** "Closes in 49m 12s" / "Starts in 1d 2h" / "Ended". */
export function Countdown({ rfq }: { rfq: RfqSummary }) {
  const now = useNow();
  const status = liveStatus(rfq, now);
  let text: string;
  let urgent = false;
  if (status === 'SCHEDULED') {
    text = `Starts in ${formatDuration(Date.parse(rfq.bid_start_at) - now)}`;
  } else if (status === 'ACTIVE') {
    const left = Date.parse(rfq.current_close_at) - now;
    urgent = left < 5 * 60_000;
    text = `Closes in ${formatDuration(left)}`;
  } else if (status === 'CANCELLED') {
    text = 'Cancelled';
  } else {
    text = 'Ended';
  }
  return (
    <Typography
      variant="body2"
      component="span"
      sx={{
        fontVariantNumeric: 'tabular-nums',
        color: urgent ? 'error.main' : 'text.secondary',
        fontWeight: urgent ? 600 : 400,
      }}
    >
      {text}
    </Typography>
  );
}

export function Money({
  amount,
  currency,
  plain = false,
}: {
  amount: string | null;
  currency: string;
  /** Regular weight (for breakdown columns). */
  plain?: boolean;
}) {
  if (amount === null) {
    return (
      <Typography component="span" color="text.disabled">
        —
      </Typography>
    );
  }
  return (
    <Typography
      component="span"
      sx={{ fontVariantNumeric: 'tabular-nums', fontWeight: plain ? 400 : 600 }}
    >
      {formatMoney(amount, currency)}
    </Typography>
  );
}

export function LabeledValue({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Stack spacing={0.25}>
      <Typography
        variant="caption"
        color="text.secondary"
        sx={{ textTransform: 'uppercase', letterSpacing: 0.4 }}
      >
        {label}
      </Typography>
      <Typography component="div">{children}</Typography>
    </Stack>
  );
}
