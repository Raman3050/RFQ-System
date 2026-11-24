import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

import { App } from './App';
import { AppProviders } from './providers';

function renderAt(path: string) {
  return render(
    <AppProviders>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </AppProviders>,
  );
}

describe('App', () => {
  it('redirects / to the auctions page', () => {
    renderAt('/');
    expect(screen.getByRole('heading', { name: 'Auctions' })).toBeInTheDocument();
  });

  it('shows dependency status on the system page', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            status: 'degraded',
            server_time: '2026-11-24T12:00:00Z',
            checks: {
              postgres: { status: 'ok', error: null },
              redis: { status: 'error', error: 'ConnectionError' },
            },
          }),
          { status: 503, headers: { 'content-type': 'application/json' } },
        ),
      ),
    );

    renderAt('/system');

    expect(await screen.findByText('degraded')).toBeInTheDocument();
    expect(screen.getByText('ConnectionError')).toBeInTheDocument();
  });
});
