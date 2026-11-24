import { zodResolver } from '@hookform/resolvers/zod';
import Alert from '@mui/material/Alert';
import Button from '@mui/material/Button';
import Link from '@mui/material/Link';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Link as RouterLink, useNavigate } from 'react-router-dom';

import { ApiError, fieldErrors } from '@/api/client';
import { FormTextField } from '@/components/FormTextField';

import { AuthCard } from './AuthCard';
import { useAuth } from './AuthContext';
import { registerSchema, type RegisterForm } from './schemas';

const FIELDS = ['full_name', 'company_name', 'email', 'password'] as const;

export function RegisterPage() {
  const { register: signUp } = useAuth();
  const navigate = useNavigate();
  const [formError, setFormError] = useState<string | null>(null);

  const {
    control,
    handleSubmit,
    setError,
    formState: { isSubmitting },
  } = useForm<RegisterForm>({
    resolver: zodResolver(registerSchema),
    defaultValues: { full_name: '', company_name: '', email: '', password: '' },
  });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      await signUp(values);
      navigate('/auctions', { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.code === 'EMAIL_TAKEN') {
        setError('email', { message: err.message });
        return;
      }
      const byField = fieldErrors(err);
      const known = FIELDS.filter((f) => byField[f]);
      known.forEach((f) => setError(f, { message: byField[f] }));
      if (known.length === 0) {
        setFormError(err instanceof ApiError ? err.message : 'Something went wrong. Try again.');
      }
    }
  });

  return (
    <AuthCard
      title="Create a buyer account"
      subtitle="Run RFQs and British Auctions. Suppliers join by invitation from a buyer."
    >
      <form onSubmit={onSubmit} noValidate>
        <Stack spacing={2}>
          {formError && <Alert severity="error">{formError}</Alert>}

          <FormTextField name="full_name" control={control} label="Full name" autoComplete="name" />
          <FormTextField
            name="company_name"
            control={control}
            label="Company"
            autoComplete="organization"
          />
          <FormTextField
            name="email"
            control={control}
            label="Work email"
            type="email"
            autoComplete="email"
          />
          <FormTextField
            name="password"
            control={control}
            label="Password"
            type="password"
            autoComplete="new-password"
            helperText="8+ characters with a letter and a digit"
          />
          <Button type="submit" variant="contained" size="large" disabled={isSubmitting}>
            {isSubmitting ? 'Creating account…' : 'Create account'}
          </Button>
          <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center' }}>
            Supplier? Use the invitation link from your email. Already registered?{' '}
            <Link component={RouterLink} to="/login">
              Sign in
            </Link>
          </Typography>
        </Stack>
      </form>
    </AuthCard>
  );
}
