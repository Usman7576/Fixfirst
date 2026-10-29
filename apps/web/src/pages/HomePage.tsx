import { useReadiness } from "../api/health";

function SystemStatus() {
  const { data, isPending, isError } = useReadiness();

  let label = "Checking…";
  let tone = "bg-slate-100 text-slate-700";
  if (isError) {
    label = "API unavailable";
    tone = "bg-red-100 text-red-800";
  } else if (!isPending) {
    label = "Operational";
    tone = "bg-emerald-100 text-emerald-800";
  }

  return (
    <section aria-labelledby="status-heading" className="rounded-lg border bg-white p-5">
      <h2 id="status-heading" className="text-sm font-medium text-slate-500">
        System status
      </h2>
      <p className="mt-2 flex items-center gap-3">
        <span role="status" className={`rounded-full px-3 py-1 text-sm font-medium ${tone}`}>
          {label}
        </span>
        {data?.migration && (
          <span className="text-sm text-slate-500">schema revision {data.migration}</span>
        )}
      </p>
    </section>
  );
}

export function HomePage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Overview</h1>
        <p className="mt-1 text-slate-600">
          Connected repositories and their latest scans will appear here.
        </p>
      </div>
      <SystemStatus />
      <p className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
        Only public repositories are supported on the free tier: code snippets are sent to
        third-party AI providers whose free plans may use submitted data.
      </p>
    </div>
  );
}
