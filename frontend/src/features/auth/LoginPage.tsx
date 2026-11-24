import { zodResolver } from '@hookform/resolvers/zod';
import Alert from '@mui/material/Alert';
import Button from '@mui/material/Button';
import Link from '@mui/material/Link';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Link as RouterLink, useLocation, useNavigate } from 'react-router-dom';

import { ApiError } from '@/api/client';
import { FormTextField } from '@/components/FormTextField';

import { AuthCard } from './AuthCard';
import { useAuth } from './AuthContext';
import { loginSchema, type LoginForm } from './schemas';

const DEMO_PASSWORD = 'Demo@12345';
const DEMO_ACCOUNTS = [
  { label: 'Buyer', email: 'buyer@example.com' },
  { label: 'Supplier 1', email: 'supplier1@example.com' },
  { label: 'Supplier 2', email: 'supplier2@example.com' },
];

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? '/auctions';
  const [formError, setFormError] = useState<string | null>(null);

  const {
    control,
    handleSubmit,
    setValue,
    formState: { isSubmitting },
  } = useForm<LoginForm>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: '', password: '' },
  });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      await login(values);
      navigate(from, { replace: true });
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : 'Something went wrong. Try again.');
    }
  });

  return (
    <AuthCard title="Sign in" subtitle="Access your RFQs and live auctions.">
      <form onSubmit={onSubmit} noValidate>
        <Stack spacing={2}>
          {formError && <Alert severity="error">{formError}</Alert>}
          <FormTextField
            name="email"
            control={control}
            label="Email"
            type="email"
            autoComplete="email"
            autoFocus
          />
          <FormTextField
            name="password"
            control={control}
            label="Password"
            type="password"
            autoComplete="current-password"
          />
          <Button type="submit" variant="contained" size="large" disabled={isSubmitting}>
            {isSubmitting ? 'Signing in…' : 'Sign in'}
          </Button>
          <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center' }}>
            New here?{' '}
            <Link component={RouterLink} to="/register">
              Create an account
            </Link>
          </Typography>
        </Stack>
      </form>

      {import.meta.env.DEV && (
        <Alert severity="info" sx={{ mt: 3 }}>
          <Typography variant="body2" sx={{ mb: 1 }}>
            Demo accounts (run <code>make seed</code>), password <code>{DEMO_PASSWORD}</code>:
          </Typography>
          <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', rowGap: 1 }}>
            {DEMO_ACCOUNTS.map((a) => (
              <Button
                key={a.email}
                size="small"
                variant="outlined"
                onClick={() => {
                  setValue('email', a.email, { shouldValidate: true });
                  setValue('password', DEMO_PASSWORD, { shouldValidate: true });
                }}
              >
                {a.label}
              </Button>
            ))}
          </Stack>
        </Alert>
      )}
    </AuthCard>
  );
}
