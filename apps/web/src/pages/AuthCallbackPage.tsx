import { Navigate } from "react-router";

import { useAuth } from "../auth/context";

/** GitHub sends the browser here after the API set the refresh cookie. */
export function AuthCallbackPage() {
  const { status } = useAuth();
  if (status === "signed_in") return <Navigate to="/" replace />;
  if (status === "signed_out") return <Navigate to="/login?error=session" replace />;
  return (
    <p role="status" className="p-8 text-slate-500">
      Signing you in…
    </p>
  );
}
