import { zodResolver } from '@hookform/resolvers/zod';
import Alert from '@mui/material/Alert';
import Button from '@mui/material/Button';
import CircularProgress from '@mui/material/CircularProgress';
import Link from '@mui/material/Link';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Link as RouterLink, useNavigate, useSearchParams } from 'react-router-dom';
import { z } from 'zod';

import { API_V1, ApiError, apiRequest, fieldErrors } from '@/api/client';
import { FormTextField } from '@/components/FormTextField';
import { formatDateTime } from '@/lib/datetime';

import { AuthCard } from './AuthCard';
import { registerSchema } from './schemas';
import * as session from './session';

interface InviteInfo {
  email: string;
  invited_by_company: string;
  expires_at: string;
}

const acceptSchema = registerSchema.pick({ full_name: true, company_name: true, password: true });
type AcceptForm = z.infer<typeof acceptSchema>;

export function AcceptInvitePage() {
  const [params] = useSearchParams();
  const token = params.get('token') ?? '';
  const navigate = useNavigate();
  const [formError, setFormError] = useState<string | null>(null);

  const invite = useQuery({
    queryKey: ['invite', token],
    queryFn: () =>
      apiRequest<InviteInfo>(`${API_V1}/auth/invitations/inspect`, {
        method: 'POST',
        json: { token },
        auth: false,
      }),
    enabled: token.length >= 20,
    retry: false,
  });

  const {
    control,
    handleSubmit,
    setError,
    formState: { isSubmitting },
  } = useForm<AcceptForm>({
    resolver: zodResolver(acceptSchema),
    defaultValues: { full_name: '', company_name: '', password: '' },
  });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      await session.acceptInvite({ token, ...values });
      navigate('/auctions', { replace: true });
    } catch (err) {
      const byField = fieldErrors(err);
      const known = (['full_name', 'company_name', 'password'] as const).filter((f) => byField[f]);
      known.forEach((f) => setError(f, { message: byField[f] }));
      if (!known.length)
        setFormError(err instanceof ApiError ? err.message : 'Something went wrong.');
    }
  });

  if (token.length < 20 || invite.isError) {
    const message =
      invite.error instanceof ApiError
        ? invite.error.message
        : 'This invitation link is incomplete. Open the link from your email again.';
    return (
      <AuthCard title="Invitation unavailable" subtitle="We couldn’t use this sign-up link.">
        <Alert severity="warning" sx={{ mb: 2 }}>
          {message}
        </Alert>
        <Button component={RouterLink} to="/login" variant="outlined" fullWidth>
          Go to sign in
        </Button>
      </AuthCard>
    );
  }

  if (invite.isPending) {
    return (
      <AuthCard title="Checking your invitation…" subtitle="One moment.">
        <CircularProgress aria-label="Loading invitation" />
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title="Join as a supplier"
      subtitle={`${invite.data.invited_by_company} invited you to quote on their RFQs.`}
    >
      <form onSubmit={onSubmit} noValidate>
        <Stack spacing={2}>
          {formError && <Alert severity="error">{formError}</Alert>}
          <TextField
            label="Email"
            value={invite.data.email}
            fullWidth
            disabled
            helperText={`Invitation valid until ${formatDateTime(invite.data.expires_at)}`}
          />
          <FormTextField
            name="full_name"
            control={control}
            label="Full name"
            autoComplete="name"
            autoFocus
          />
          <FormTextField
            name="company_name"
            control={control}
            label="Company (carrier)"
            autoComplete="organization"
          />
          <FormTextField
            name="password"
            control={control}
            label="Choose a password"
            type="password"
            autoComplete="new-password"
            helperText="8+ characters with a letter and a digit"
          />
          <Button type="submit" variant="contained" size="large" disabled={isSubmitting}>
            {isSubmitting ? 'Creating account…' : 'Create supplier account'}
          </Button>
          <Link component={RouterLink} to="/login" variant="body2" sx={{ textAlign: 'center' }}>
            Already have an account? Sign in
          </Link>
        </Stack>
      </form>
    </AuthCard>
  );
}
