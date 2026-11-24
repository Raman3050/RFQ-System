import { Navigate, Route, Routes } from 'react-router-dom';

import { ComingSoon } from '@/components/ComingSoon';
import { Layout } from '@/components/Layout';
import { RedirectIfAuthenticated, RequireAuth } from '@/features/auth/guards';
import { LoginPage } from '@/features/auth/LoginPage';
import { RegisterPage } from '@/features/auth/RegisterPage';
import { HomePage } from '@/features/home/HomePage';
import { SystemStatusPage } from '@/features/system/SystemStatusPage';

export function App() {
  return (
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
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<Navigate to="/auctions" replace />} />
        <Route path="auctions" element={<HomePage />} />
        <Route path="auctions/:rfqId" element={<ComingSoon title="Auction details" phase={3} />} />
        <Route
          path="rfqs/new"
          element={
            <RequireAuth roles={['BUYER', 'ADMIN']}>
              <ComingSoon title="Create RFQ" phase={2} />
            </RequireAuth>
          }
        />
        <Route
          path="system"
          element={
            <RequireAuth roles={['BUYER', 'ADMIN']}>
              <SystemStatusPage />
            </RequireAuth>
          }
        />
        <Route path="*" element={<ComingSoon title="Page not found" phase={0} />} />
      </Route>
    </Routes>
  );
}
