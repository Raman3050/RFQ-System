import Box from '@mui/material/Box';
import CircularProgress from '@mui/material/CircularProgress';
import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';

import { ForbiddenPage } from '@/components/ForbiddenPage';

import { useAuth } from './AuthContext';
import type { Role } from './types';

export function FullPageSpinner() {
  return (
    <Box sx={{ display: 'grid', placeItems: 'center', minHeight: '60vh' }}>
      <CircularProgress aria-label="Loading" />
    </Box>
  );
}

/** Renders children only for signed-in users (optionally with one of `roles`). */
export function RequireAuth({ children, roles }: { children: ReactNode; roles?: Role[] }) {
  const { status, hasRole } = useAuth();
  const location = useLocation();

  if (status === 'loading') return <FullPageSpinner />;
  if (status === 'anonymous') {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  }
  if (roles && !hasRole(...roles)) return <ForbiddenPage />;
  return <>{children}</>;
}

/** For /login and /register: signed-in users are sent on to the app. */
export function RedirectIfAuthenticated({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  if (status === 'loading') return <FullPageSpinner />;
  if (status === 'authenticated') return <Navigate to="/auctions" replace />;
  return <>{children}</>;
}
