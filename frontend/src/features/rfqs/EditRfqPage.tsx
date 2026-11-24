import Alert from '@mui/material/Alert';
import Button from '@mui/material/Button';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import { useMemo } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { ApiError } from '@/api/client';
import { FullPageSpinner } from '@/features/auth/guards';

import { useRfq, useUpdateRfq } from './api';
import { RfqForm } from './form/RfqForm';
import { formValuesFromRfq, toWrite } from './form/schema';

export function EditRfqPage() {
  const { rfqId = '' } = useParams();
  const navigate = useNavigate();
  const { data: rfq, isPending, error, refetch } = useRfq(rfqId);
  const update = useUpdateRfq(rfqId);
  const defaults = useMemo(() => (rfq ? formValuesFromRfq(rfq) : null), [rfq]);

  if (isPending) return <FullPageSpinner />;
  if (error || !rfq || !defaults) {
    return <Alert severity="error">{error?.message ?? 'RFQ not found'}</Alert>;
  }
  if (!rfq.permissions.can_edit) {
    return (
      <Alert
        severity="warning"
        action={
          <Button component={Link} to={`/auctions/${rfq.id}`} color="inherit">
            View RFQ
          </Button>
        }
      >
        This RFQ can no longer be edited — bidding has started or it was cancelled.
      </Alert>
    );
  }

  return (
    <Stack spacing={3}>
      <div>
        <Typography variant="overline" color="text.secondary">
          {rfq.reference_id}
        </Typography>
        <Typography variant="h4" component="h1">
          Edit RFQ
        </Typography>
      </div>
      {update.error instanceof ApiError && update.error.status === 412 && (
        <Alert
          severity="warning"
          action={
            <Button color="inherit" onClick={() => void refetch().then(() => update.reset())}>
              Reload
            </Button>
          }
        >
          Someone else changed this RFQ while you were editing. Reload to get the latest version.
        </Alert>
      )}
      <RfqForm
        key={rfq.version}
        mode="edit"
        defaultValues={defaults}
        submitLabel="Save changes"
        onCancel={() => navigate(`/auctions/${rfq.id}`)}
        onSubmit={async (values) => {
          await update.mutateAsync({ input: toWrite(values), version: rfq.version });
          navigate(`/auctions/${rfq.id}`, { replace: true });
        }}
      />
    </Stack>
  );
}
