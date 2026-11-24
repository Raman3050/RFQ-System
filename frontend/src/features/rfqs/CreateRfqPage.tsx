import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';

import { useCreateRfq } from './api';
import { RfqForm } from './form/RfqForm';
import { defaultFormValues, toCreate } from './form/schema';

export function CreateRfqPage() {
  const navigate = useNavigate();
  const create = useCreateRfq();
  const defaults = useMemo(() => defaultFormValues(), []);

  return (
    <Stack spacing={3}>
      <div>
        <Typography variant="h4" component="h1">
          Create RFQ
        </Typography>
        <Typography color="text.secondary">
          Set the bidding schedule and British Auction rules, then invite suppliers.
        </Typography>
      </div>
      <RfqForm
        mode="create"
        defaultValues={defaults}
        submitLabel="Create RFQ"
        onCancel={() => navigate('/auctions')}
        onSubmit={async (values) => {
          const rfq = await create.mutateAsync(toCreate(values));
          navigate(`/auctions/${rfq.id}`, { replace: true, state: { created: true } });
        }}
      />
    </Stack>
  );
}
