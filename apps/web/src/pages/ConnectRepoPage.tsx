import { useState } from "react";
import { useNavigate } from "react-router";

import { ApiError } from "../api/client";
import { useAvailableRepos, useConnectRepo } from "../api/queries";
import { useAuth } from "../auth/context";

export function ConnectRepoPage() {
  const { me } = useAuth();
  const team = me?.teams[0];
  const available = useAvailableRepos();
  const connect = useConnectRepo(team?.team_id);
  const navigate = useNavigate();
  const [filter, setFilter] = useState("");

  const repos = (available.data ?? []).filter((r) =>
    r.full_name.toLowerCase().includes(filter.trim().toLowerCase()),
  );
  const error = connect.error instanceof ApiError ? connect.error.message : null;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Connect a repository</h1>
        <p className="mt-1 text-slate-600">Pick one of your GitHub repositories to scan.</p>
      </div>
      <p className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
        Only public repositories are supported on the free tier: code snippets are sent to
        third-party AI providers whose free plans may use submitted data.
      </p>
      <label className="block">
        <span className="sr-only">Filter repositories</span>
        <input
          type="search"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter repositories"
          className="w-full rounded-md border px-3 py-2"
        />
      </label>
      {error && (
        <p role="alert" className="text-red-700">
          {error}
        </p>
      )}
      {available.isPending && <p className="text-slate-500">Loading your repositories…</p>}
      {available.isError && (
        <p role="alert" className="text-red-700">
          Couldn't load your GitHub repositories.
        </p>
      )}
      <ul className="divide-y rounded-lg border bg-white">
        {repos.map((repo) => (
          <li
            key={repo.github_repo_id}
            className="flex items-center justify-between gap-4 px-4 py-3"
          >
            <div className="min-w-0">
              <p className="truncate font-medium">{repo.full_name}</p>
              <p className="text-sm text-slate-500">{repo.language ?? "Unknown language"}</p>
            </div>
            {repo.connectable ? (
              <button
                type="button"
                disabled={connect.isPending}
                onClick={() => connect.mutate(repo.full_name, { onSuccess: () => navigate("/") })}
                className="shrink-0 rounded-md border px-3 py-1.5 text-sm font-medium hover:bg-slate-50 disabled:opacity-50"
              >
                Connect
              </button>
            ) : (
              <span className="shrink-0 text-sm text-slate-400">Private: not supported</span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
