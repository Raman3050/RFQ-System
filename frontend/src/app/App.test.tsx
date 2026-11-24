import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it } from 'vitest';

import { resetSession } from '@/features/auth/session';
import { ANON_REFRESH, authResponse, json, makeUser, mockApi, problem } from '@/test/mockApi';

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

const restoredAs = (role: 'BUYER' | 'SUPPLIER') => ({
  'POST /api/v1/auth/refresh': () => json(authResponse(makeUser(role))),
});

describe('App auth flows', () => {
  beforeEach(() => resetSession());

  it('sends anonymous visitors to the login page', async () => {
    mockApi(ANON_REFRESH);
    renderAt('/auctions');
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
  });

  it('logs a buyer in and shows the buyer home page', async () => {
    const fetchMock = mockApi({
      ...ANON_REFRESH,
      'POST /api/v1/auth/login': () => json(authResponse(makeUser('BUYER'))),
    });
    const user = userEvent.setup();
    renderAt('/auctions');

    await user.type(await screen.findByLabelText('Email'), 'buyer@example.com');
    await user.type(screen.getByLabelText('Password'), 'Demo@12345');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByRole('heading', { name: /Welcome, Priya/ })).toBeInTheDocument();
    expect(screen.getByText('Create an RFQ')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Create RFQ' })).toBeInTheDocument();

    const loginCall = fetchMock.mock.calls.find(([url]) => url === '/api/v1/auth/login');
    expect(JSON.parse(String(loginCall?.[1]?.body))).toEqual({
      email: 'buyer@example.com',
      password: 'Demo@12345',
    });
  });

  it('shows the server error for bad credentials', async () => {
    mockApi({
      ...ANON_REFRESH,
      'POST /api/v1/auth/login': () =>
        problem(401, 'INVALID_CREDENTIALS', 'Invalid email or password'),
    });
    const user = userEvent.setup();
    renderAt('/login');

    await user.type(await screen.findByLabelText('Email'), 'buyer@example.com');
    await user.type(screen.getByLabelText('Password'), 'wrong');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByText('Invalid email or password')).toBeInTheDocument();
  });

  it('demo-account buttons fill the login form', async () => {
    mockApi(ANON_REFRESH);
    const user = userEvent.setup();
    renderAt('/login');

    await user.click(await screen.findByRole('button', { name: 'Supplier 1' }));

    expect(screen.getByLabelText('Email')).toHaveValue('supplier1@example.com');
    expect(screen.getByLabelText('Password')).toHaveValue('Demo@12345');
  });

  it('validates the login form before calling the API', async () => {
    const fetchMock = mockApi(ANON_REFRESH);
    const user = userEvent.setup();
    renderAt('/login');

    await user.click(await screen.findByRole('button', { name: 'Sign in' }));

    expect(await screen.findByText('Enter a valid email address')).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => url === '/api/v1/auth/login')).toBe(false);
  });

  it('restores the session from the refresh cookie and shows the supplier home', async () => {
    mockApi(restoredAs('SUPPLIER'));
    renderAt('/auctions');

    expect(await screen.findByRole('heading', { name: /Welcome, Arjun/ })).toBeInTheDocument();
    expect(screen.getByText('Submit and lower bids')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Create RFQ' })).not.toBeInTheDocument();
  });

  it('blocks suppliers from buyer-only pages', async () => {
    mockApi(restoredAs('SUPPLIER'));
    renderAt('/rfqs/new');
    expect(
      await screen.findByRole('heading', { name: 'Not available for your role' }),
    ).toBeInTheDocument();
  });

  it('redirects signed-in users away from /login', async () => {
    mockApi(restoredAs('BUYER'));
    renderAt('/login');
    expect(await screen.findByRole('heading', { name: /Welcome, Priya/ })).toBeInTheDocument();
  });

  it('registers a supplier', async () => {
    const fetchMock = mockApi({
      ...ANON_REFRESH,
      'POST /api/v1/auth/register': () => json(authResponse(makeUser('SUPPLIER')), 201),
    });
    const user = userEvent.setup();
    renderAt('/register');

    await user.click(await screen.findByRole('button', { name: 'Supplier' }));
    await user.type(screen.getByLabelText('Full name'), 'Arjun Mehta');
    await user.type(screen.getByLabelText('Company'), 'BlueDart Freight');
    await user.type(screen.getByLabelText('Work email'), 'supplier@example.com');
    await user.type(screen.getByLabelText('Password'), 'Secret123');
    await user.click(screen.getByRole('button', { name: 'Create account' }));

    expect(await screen.findByRole('heading', { name: /Welcome, Arjun/ })).toBeInTheDocument();
    const call = fetchMock.mock.calls.find(([url]) => url === '/api/v1/auth/register');
    expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({ role: 'SUPPLIER' });
  });

  it('shows EMAIL_TAKEN on the email field', async () => {
    mockApi({
      ...ANON_REFRESH,
      'POST /api/v1/auth/register': () =>
        problem(409, 'EMAIL_TAKEN', 'An account with this email already exists'),
    });
    const user = userEvent.setup();
    renderAt('/register');

    await user.type(await screen.findByLabelText('Full name'), 'Priya');
    await user.type(screen.getByLabelText('Company'), 'Acme');
    await user.type(screen.getByLabelText('Work email'), 'buyer@example.com');
    await user.type(screen.getByLabelText('Password'), 'Secret123');
    await user.click(screen.getByRole('button', { name: 'Create account' }));

    expect(
      await screen.findByText('An account with this email already exists'),
    ).toBeInTheDocument();
  });

  it('signs out back to the login page', async () => {
    mockApi({
      ...restoredAs('BUYER'),
      'POST /api/v1/auth/logout': () => new Response(null, { status: 204 }),
    });
    const user = userEvent.setup();
    renderAt('/auctions');

    await user.click(await screen.findByRole('button', { name: 'Account menu' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Sign out' }));

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Sign in' })).toBeInTheDocument(),
    );
  });

  it('shows dependency status on the system page for buyers', async () => {
    mockApi({
      ...restoredAs('BUYER'),
      'GET /health/ready': () =>
        json(
          {
            status: 'degraded',
            server_time: '2026-11-24T12:00:00Z',
            checks: {
              postgres: { status: 'ok', error: null },
              redis: { status: 'error', error: 'ConnectionError' },
            },
          },
          503,
        ),
    });
    renderAt('/system');

    expect(await screen.findByText('degraded')).toBeInTheDocument();
    expect(screen.getByText('ConnectionError')).toBeInTheDocument();
  });
});
