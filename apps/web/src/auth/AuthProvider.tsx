import { useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import { Navigate, useLocation } from "react-router";

import { ApiError, refreshAccessToken, signOut as apiSignOut } from "../api/client";
import { useMe } from "../api/queries";
import { AuthContext, type AuthStatus, useAuth } from "./context";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const queryClient = useQueryClient();
  const me = useMe(status === "signed_in");

  useEffect(() => {
    // Restores the session from the refresh cookie on every page load.
    let cancelled = false;
    void refreshAccessToken().then((token) => {
      if (!cancelled) setStatus(token ? "signed_in" : "signed_out");
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const signOut = useCallback(async () => {
    await apiSignOut();
    queryClient.clear();
    setStatus("signed_out");
  }, [queryClient]);

  // A 401 that survived the silent refresh means the session ended (expired or revoked).
  const sessionEnded = me.error instanceof ApiError && me.error.status === 401;
  const effective: AuthStatus = sessionEnded ? "signed_out" : status;
  const value = useMemo(
    () => ({ status: effective, me: me.data, signOut }),
    [effective, me.data, signOut],
  );
  return <AuthContext value={value}>{children}</AuthContext>;
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const location = useLocation();
  if (status === "loading") {
    return (
      <p role="status" className="p-8 text-slate-500">
        Loading…
      </p>
    );
  }
  if (status === "signed_out") return <Navigate to="/login" replace state={{ from: location }} />;
  return children;
}
