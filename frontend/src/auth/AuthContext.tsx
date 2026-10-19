import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { ApiError, SESSION_EXPIRED_EVENT, authApi, tokens } from "@/lib/api";
import type { User } from "@/lib/types";

interface AuthContextValue {
  user: User | null;
  status: "loading" | "authenticated" | "anonymous";
  login: (email: string, password: string) => Promise<void>;
  register: (payload: {
    email: string;
    full_name: string;
    password: string;
    department?: string;
    institution?: string;
  }) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [status, setStatus] = useState<AuthContextValue["status"]>("loading");

  const loadSession = useCallback(async () => {
    if (!tokens.access()) {
      setUser(null);
      setStatus("anonymous");
      return;
    }
    try {
      const me = await authApi.me();
      setUser(me);
      setStatus("authenticated");
    } catch (err) {
      // A 401 here already cleared tokens and fired the expiry event; anything
      // else (network blip) should not silently sign the user out.
      if (err instanceof ApiError && err.status === 401) {
        tokens.clear();
      }
      setUser(null);
      setStatus("anonymous");
    }
  }, []);

  useEffect(() => {
    void loadSession();
  }, [loadSession]);

  useEffect(() => {
    const onExpired = () => {
      setUser(null);
      setStatus("anonymous");
    };
    window.addEventListener(SESSION_EXPIRED_EVENT, onExpired);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, onExpired);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const data = await authApi.login(email, password);
    tokens.set(data.access_token, data.refresh_token);
    setUser(data.user);
    setStatus("authenticated");
  }, []);

  const register = useCallback<AuthContextValue["register"]>(async (payload) => {
    const data = await authApi.register(payload);
    tokens.set(data.access_token, data.refresh_token);
    setUser(data.user);
    setStatus("authenticated");
  }, []);

  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } catch {
      /* best-effort: always clear locally */
    }
    tokens.clear();
    setUser(null);
    setStatus("anonymous");
  }, []);

  const refreshUser = useCallback(async () => {
    const me = await authApi.me();
    setUser(me);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ user, status, login, register, logout, refreshUser }),
    [user, status, login, register, logout, refreshUser],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
