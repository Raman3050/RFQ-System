import Alert from '@mui/material/Alert';
import Button from '@mui/material/Button';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogContentText from '@mui/material/DialogContentText';
import DialogTitle from '@mui/material/DialogTitle';
import Grid from '@mui/material/Grid';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import { useState } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';

import { ApiError } from '@/api/client';
import { FullPageSpinner } from '@/features/auth/guards';
import { formatDate, formatDateTime, formatMinutes } from '@/lib/datetime';

import { useCancelRfq, useRfq } from './api';
import { Countdown, LabeledValue, LiveStatusBadge, Money } from './components';
import { InvitationsCard } from './InvitationsCard';
import { TRIGGER_LABEL, type RfqDetail } from './types';

function ScheduleCard({ rfq }: { rfq: RfqDetail }) {
  const extended = rfq.current_close_at !== rfq.bid_close_at;
  return (
    <Paper variant="outlined" sx={{ p: { xs: 2, sm: 3 }, height: '100%' }}>
      <Typography variant="h6" component="h2" sx={{ mb: 2 }}>
        Schedule
      </Typography>
      <Grid container spacing={2}>
        <Grid size={{ xs: 12, sm: 6 }}>
          <LabeledValue label="Bid start">{formatDateTime(rfq.bid_start_at)}</LabeledValue>
        </Grid>
        <Grid size={{ xs: 12, sm: 6 }}>
          <LabeledValue label={extended ? 'Current bid close (extended)' : 'Bid close'}>
            {formatDateTime(rfq.current_close_at)}
            {extended && (
              <Typography variant="body2" color="text.secondary">
                originally {formatDateTime(rfq.bid_close_at)}
              </Typography>
            )}
          </LabeledValue>
        </Grid>
        <Grid size={{ xs: 12, sm: 6 }}>
          <LabeledValue label="Forced close">{formatDateTime(rfq.forced_close_at)}</LabeledValue>
        </Grid>
        <Grid size={{ xs: 12, sm: 6 }}>
          <LabeledValue label="Pickup / service date">{formatDate(rfq.pickup_date)}</LabeledValue>
        </Grid>
      </Grid>
    </Paper>
  );
}

function AuctionConfigCard({ rfq }: { rfq: RfqDetail }) {
  const cfg = rfq.auction_config;
  return (
    <Paper variant="outlined" sx={{ p: { xs: 2, sm: 3 }, height: '100%' }}>
      <Typography variant="h6" component="h2" sx={{ mb: 2 }}>
        Auction rules
      </Typography>
      {cfg ? (
        <Stack spacing={2}>
          <Grid container spacing={2}>
            <Grid size={6}>
              <LabeledValue label="Trigger window (X)">
                {formatMinutes(cfg.trigger_window_minutes)}
              </LabeledValue>
            </Grid>
            <Grid size={6}>
              <LabeledValue label="Extension (Y)">
                {formatMinutes(cfg.extension_minutes)}
              </LabeledValue>
            </Grid>
          </Grid>
          <LabeledValue label="Extends when">
            {TRIGGER_LABEL[cfg.trigger_type].title}
            <Typography variant="body2" color="text.secondary">
              {TRIGGER_LABEL[cfg.trigger_type].description}
            </Typography>
          </LabeledValue>
          <LabeledValue label="Extensions so far">{rfq.extension_count}</LabeledValue>
        </Stack>
      ) : (
        <Typography color="text.secondary">
          Not a British Auction — the close time is fixed and never extended.
        </Typography>
      )}
    </Paper>
  );
}

export function RfqDetailPage() {
  const { rfqId = '' } = useParams();
  const location = useLocation();
  const justCreated = (location.state as { created?: boolean } | null)?.created;
  const { data: rfq, isPending, error } = useRfq(rfqId);
  const cancel = useCancelRfq(rfqId);
  const [confirmCancel, setConfirmCancel] = useState(false);

  if (isPending) return <FullPageSpinner />;
  if (error || !rfq) {
    const notFound = error instanceof ApiError && error.status === 404;
    return (
      <Alert
        severity={notFound ? 'warning' : 'error'}
        action={
          <Button component={Link} to="/auctions" color="inherit">
            All auctions
          </Button>
        }
      >
        {notFound ? 'This RFQ does not exist or you do not have access to it.' : error?.message}
      </Alert>
    );
  }

  return (
    <Stack spacing={3}>
      {justCreated && (
        <Alert severity="success">
          {rfq.reference_id} created.{' '}
          {rfq.invited_count > 0 && `Invitations sent to ${rfq.invited_count} supplier(s).`}
        </Alert>
      )}

      <Stack
        direction={{ xs: 'column', md: 'row' }}
        spacing={2}
        sx={{ justifyContent: 'space-between', alignItems: { md: 'flex-start' } }}
      >
        <div>
          <Typography variant="overline" color="text.secondary">
            {rfq.reference_id} · {rfq.buyer.company_name}
          </Typography>
          <Stack direction="row" spacing={1.5} sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
            <Typography variant="h4" component="h1">
              {rfq.name}
            </Typography>
            <LiveStatusBadge rfq={rfq} size="medium" />
          </Stack>
          <Countdown rfq={rfq} />
        </div>
        <Stack direction="row" spacing={1}>
          {rfq.permissions.can_edit && (
            <Button component={Link} to={`/rfqs/${rfq.id}/edit`} variant="outlined">
              Edit
            </Button>
          )}
          {rfq.permissions.can_cancel && (
            <Button color="error" onClick={() => setConfirmCancel(true)}>
              Cancel RFQ
            </Button>
          )}
        </Stack>
      </Stack>

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, md: 7 }}>
          <ScheduleCard rfq={rfq} />
        </Grid>
        <Grid size={{ xs: 12, md: 5 }}>
          <AuctionConfigCard rfq={rfq} />
        </Grid>
      </Grid>

      <Paper variant="outlined" sx={{ p: { xs: 2, sm: 3 } }}>
        <Stack direction="row" sx={{ justifyContent: 'space-between', alignItems: 'baseline' }}>
          <Typography variant="h6" component="h2">
            Bids
          </Typography>
          <Typography>
            Lowest: <Money amount={rfq.current_lowest_bid} currency={rfq.currency} />
          </Typography>
        </Stack>
        <Typography color="text.secondary" sx={{ mt: 1 }}>
          Ranked bids (L1, L2, …), quote details and the activity log arrive in Phase 3.
        </Typography>
      </Paper>

      {rfq.invitations && <InvitationsCard rfq={rfq} />}

      <Dialog open={confirmCancel} onClose={() => setConfirmCancel(false)}>
        <DialogTitle>Cancel {rfq.reference_id}?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            Suppliers will no longer be able to bid. This cannot be undone.
          </DialogContentText>
          {cancel.error && (
            <Alert severity="error" sx={{ mt: 2 }}>
              {cancel.error.message}
            </Alert>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmCancel(false)}>Keep RFQ</Button>
          <Button
            color="error"
            variant="contained"
            disabled={cancel.isPending}
            onClick={() =>
              cancel.mutateAsync(rfq.version).then(
                () => setConfirmCancel(false),
                () => undefined,
              )
            }
          >
            Cancel RFQ
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
