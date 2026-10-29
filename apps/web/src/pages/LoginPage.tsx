import { Navigate, useSearchParams } from "react-router";

import { loginUrl } from "../api/client";
import { useAuth } from "../auth/context";

const ERRORS: Record<string, string> = {
  access_denied: "GitHub sign-in was cancelled.",
  invalid_state: "Your sign-in link expired or was already used. Please try again.",
  invalid_request: "Sign-in could not be completed. Please try again.",
  github_error: "GitHub didn't accept the sign-in. Please try again.",
  session: "Your session ended. Please sign in again.",
};

export function LoginPage() {
  const { status } = useAuth();
  const [params] = useSearchParams();
  const error = params.get("error");

  if (status === "signed_in") return <Navigate to="/" replace />;

  return (
    <div className="mx-auto mt-24 max-w-sm rounded-lg border bg-white p-8 text-center">
      <h1 className="text-2xl font-semibold">Fixfirst</h1>
      <p className="mt-2 text-slate-600">Know which security findings to fix first.</p>
      {error && (
        <p role="alert" className="mt-6 rounded-md bg-red-50 p-3 text-sm text-red-800">
          {ERRORS[error] ?? ERRORS.invalid_request}
        </p>
      )}
      <a
        href={loginUrl}
        className="mt-6 inline-block w-full rounded-md bg-slate-900 px-4 py-2.5 font-medium text-white hover:bg-slate-700"
      >
        Sign in with GitHub
      </a>
      <p className="mt-4 text-xs text-slate-500">
        We only ask to read your public profile and email.
      </p>
    </div>
  );
}
