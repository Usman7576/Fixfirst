import { Link, Outlet } from "react-router";

import { useAuth } from "../auth/context";

export function Layout() {
  const { me, signOut } = useAuth();

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
          <Link to="/" className="font-semibold text-slate-900">
            Fixfirst
          </Link>
          {me && (
            <div className="flex items-center gap-3 text-sm">
              {me.avatar_url && <img src={me.avatar_url} alt="" className="h-7 w-7 rounded-full" />}
              <span className="text-slate-700">{me.login}</span>
              <button
                type="button"
                onClick={() => void signOut()}
                className="text-slate-500 underline-offset-2 hover:underline"
              >
                Sign out
              </button>
            </div>
          )}
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-8">
        <Outlet />
      </main>
    </div>
  );
}
