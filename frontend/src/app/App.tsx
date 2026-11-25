import { lazy, Suspense } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';

import { Layout } from '@/components/Layout';
import { NotFoundPage } from '@/components/NotFoundPage';
import { FullPageSpinner, RedirectIfAuthenticated, RequireAuth } from '@/features/auth/guards';
import { LoginPage } from '@/features/auth/LoginPage';

// Code-split everything past the login screen.
const lazyNamed = <K extends string>(
  load: () => Promise<Record<K, React.ComponentType>>,
  name: K,
) => lazy(() => load().then((m) => ({ default: m[name] })));

const RegisterPage = lazyNamed(() => import('@/features/auth/RegisterPage'), 'RegisterPage');
const AcceptInvitePage = lazyNamed(
  () => import('@/features/auth/AcceptInvitePage'),
  'AcceptInvitePage',
);
const AuctionListPage = lazyNamed(
  () => import('@/features/rfqs/AuctionListPage'),
  'AuctionListPage',
);
const RfqDetailPage = lazyNamed(() => import('@/features/rfqs/RfqDetailPage'), 'RfqDetailPage');
const CreateRfqPage = lazyNamed(() => import('@/features/rfqs/CreateRfqPage'), 'CreateRfqPage');
const EditRfqPage = lazyNamed(() => import('@/features/rfqs/EditRfqPage'), 'EditRfqPage');
const SystemStatusPage = lazyNamed(
  () => import('@/features/system/SystemStatusPage'),
  'SystemStatusPage',
);

const BUYER_ROLES = ['BUYER', 'ADMIN'] as const;

export function App() {
  return (
    <Suspense fallback={<FullPageSpinner />}>
      <Routes>
        <Route
          path="login"
          element={
            <RedirectIfAuthenticated>
              <LoginPage />
            </RedirectIfAuthenticated>
          }
        />
        <Route
          path="register"
          element={
            <RedirectIfAuthenticated>
              <RegisterPage />
            </RedirectIfAuthenticated>
          }
        />
        <Route
          path="accept-invite"
          element={
            <RedirectIfAuthenticated>
              <AcceptInvitePage />
            </RedirectIfAuthenticated>
          }
        />

        <Route
          element={
            <RequireAuth>
              <Layout />
            </RequireAuth>
          }
        >
          <Route index element={<Navigate to="/auctions" replace />} />
          <Route path="auctions" element={<AuctionListPage />} />
          <Route path="auctions/:rfqId" element={<RfqDetailPage />} />
          <Route
            path="rfqs/new"
            element={
              <RequireAuth roles={[...BUYER_ROLES]}>
                <CreateRfqPage />
              </RequireAuth>
            }
          />
          <Route
            path="rfqs/:rfqId/edit"
            element={
              <RequireAuth roles={[...BUYER_ROLES]}>
                <EditRfqPage />
              </RequireAuth>
            }
          />
          <Route
            path="system"
            element={
              <RequireAuth roles={[...BUYER_ROLES]}>
                <SystemStatusPage />
              </RequireAuth>
            }
          />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
