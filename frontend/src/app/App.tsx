import { Navigate, Route, Routes } from 'react-router-dom';

import { ComingSoon } from '@/components/ComingSoon';
import { Layout } from '@/components/Layout';
import { SystemStatusPage } from '@/features/system/SystemStatusPage';

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/auctions" replace />} />
        <Route path="auctions" element={<ComingSoon title="Auctions" phase={2} />} />
        <Route path="auctions/:rfqId" element={<ComingSoon title="Auction details" phase={3} />} />
        <Route path="rfqs/new" element={<ComingSoon title="Create RFQ" phase={2} />} />
        <Route path="system" element={<SystemStatusPage />} />
        <Route path="*" element={<ComingSoon title="Page not found" phase={0} />} />
      </Route>
    </Routes>
  );
}
