import { createContext, useContext } from "react";

import type { Me } from "../api/queries";

export type AuthStatus = "loading" | "signed_in" | "signed_out";

export interface AuthContextValue {
  status: AuthStatus;
  me: Me | undefined;
  signOut: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}
