import '@testing-library/jest-dom/vitest';
import { cleanup, configure } from '@testing-library/react';
import { afterEach, beforeEach, vi } from 'vitest';

import { liveClient } from '@/features/realtime/liveClient';

import { FakeWebSocket } from './fakeWebSocket';

// Pages are lazy-loaded; under parallel test load the first import can exceed 1s.
configure({ asyncUtilTimeout: 5000 });

beforeEach(() => {
  FakeWebSocket.reset();
  vi.stubGlobal('WebSocket', FakeWebSocket);
});

afterEach(() => {
  cleanup();
  liveClient.shutdown();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
