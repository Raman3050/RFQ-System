import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';

import { setAuthHandlers } from '@/api/client';

import { AuthContext, type AuthContextValue, type AuthStatus } from './AuthContext';
import * as session from './session';
import type { AuthResponse, Role, User } from './types';

/** Refresh this long before the access token expires. */
const REFRESH_LEEWAY_MS = 60_000;

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<AuthStatus>('loading');
  const [user, setUser] = useState<User | null>(null);
  const [expiresIn, setExpiresIn] = useState<number | null>(null);

  // Mirror the session module into React state.
  useEffect(() => {
    const onChange = (s: AuthResponse | null) => {
      setUser(s?.user ?? null);
      setExpiresIn(s?.expires_in ?? null);
      setStatus(s ? 'authenticated' : 'anonymous');
      if (!s) queryClient.clear(); // never show one user's cached data to the next
    };
    const unsubscribe = session.subscribe(onChange);
    setAuthHandlers({
      getAccessToken: session.getAccessToken,
      refreshAccessToken: async () => (await session.refresh())?.access_token ?? null,
    });
    // Restore the session from the refresh cookie on first load.
    void session.refresh();
    return () => {
      unsubscribe();
      setAuthHandlers(null);
    };
  }, [queryClient]);

  // Proactively refresh shortly before the access token expires.
  useEffect(() => {
    if (expiresIn === null) return;
    const delay = Math.max(expiresIn * 1000 - REFRESH_LEEWAY_MS, 5_000);
    const timer = window.setTimeout(() => void session.refresh(), delay);
    return () => window.clearTimeout(timer);
  }, [expiresIn]);

  const login = useCallback<AuthContextValue['login']>(
    async (input) => (await session.login(input)).user,
    [],
  );
  const register = useCallback<AuthContextValue['register']>(
    async (input) => (await session.register(input)).user,
    [],
  );
  const logout = useCallback(() => session.logout(), []);
  const hasRole = useCallback((...roles: Role[]) => !!user && roles.includes(user.role), [user]);

  const value = useMemo<AuthContextValue>(
    () => ({ status, user, login, register, logout, hasRole }),
    [status, user, login, register, logout, hasRole],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
