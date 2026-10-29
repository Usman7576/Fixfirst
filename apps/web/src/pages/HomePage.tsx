import { Link } from "react-router";

import { ApiError } from "../api/client";
import {
  ACTIVE_STATUSES,
  type Repo,
  type ScanSummary,
  useRepos,
  useStartScan,
} from "../api/queries";
import { useAuth } from "../auth/context";

const STATUS_STYLE: Record<ScanSummary["status"], string> = {
  queued: "bg-slate-100 text-slate-700",
  running: "bg-blue-100 text-blue-800",
  waiting_quota: "bg-amber-100 text-amber-800",
  done: "bg-emerald-100 text-emerald-800",
  failed: "bg-red-100 text-red-800",
  cancelled: "bg-slate-100 text-slate-500",
};

function ScanBadge({ scan }: { scan: ScanSummary | null }) {
  if (!scan) return <span className="text-sm text-slate-400">Never scanned</span>;
  return (
    <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_STYLE[scan.status]}`}>
      {scan.status.replace("_", " ")}
    </span>
  );
}

function RepoRow({ repo, canScan, teamId }: { repo: Repo; canScan: boolean; teamId: string }) {
  const startScan = useStartScan(teamId);
  const active = repo.latest_scan !== null && ACTIVE_STATUSES.includes(repo.latest_scan.status);
  const error = startScan.error instanceof ApiError ? startScan.error.message : null;

  return (
    <li className="flex items-center justify-between gap-4 px-4 py-3">
      <div className="min-w-0">
        <p className="truncate font-medium">{repo.github_full_name}</p>
        <p className="text-sm text-slate-500">
          {repo.language ?? "Unknown language"} · {repo.default_branch}
        </p>
        {error && <p className="mt-1 text-sm text-red-700">{error}</p>}
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <ScanBadge scan={repo.latest_scan} />
        {canScan && (
          <button
            type="button"
            disabled={active || startScan.isPending}
            onClick={() => startScan.mutate(repo.id)}
            className="rounded-md border px-3 py-1.5 text-sm font-medium hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {active ? "Scanning…" : "Scan"}
          </button>
        )}
      </div>
    </li>
  );
}

export function HomePage() {
  const { me } = useAuth();
  const team = me?.teams[0];
  const repos = useRepos(team?.team_id);
  const canScan = team?.role === "admin" || team?.role === "developer";

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Repositories</h1>
          {team && <p className="mt-1 text-slate-600">{team.team_name}</p>}
        </div>
        {team?.role === "admin" && (
          <Link
            to="/repos/connect"
            className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700"
          >
            Connect repository
          </Link>
        )}
      </div>

      {repos.isPending && team && <p className="text-slate-500">Loading repositories…</p>}
      {repos.isError && (
        <p role="alert" className="text-red-700">
          Couldn't load repositories.
        </p>
      )}
      {repos.data?.length === 0 && (
        <p className="rounded-lg border border-dashed bg-white p-8 text-center text-slate-600">
          No repositories yet. Connect a public GitHub repository to run your first scan.
        </p>
      )}
      {repos.data && repos.data.length > 0 && team && (
        <ul className="divide-y rounded-lg border bg-white">
          {repos.data.map((repo) => (
            <RepoRow key={repo.id} repo={repo} canScan={canScan} teamId={team.team_id} />
          ))}
        </ul>
      )}
    </div>
  );
}
