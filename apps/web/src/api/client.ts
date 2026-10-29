export const API_URL = (import.meta.env.VITE_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

/** RFC 9457 problem details, as returned by every API error. */
export interface Problem {
  type: string;
  title: string;
  status: number;
  detail?: string;
  request_id?: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly problem: Problem | null;

  constructor(status: number, problem: Problem | null) {
    super(problem?.detail ?? problem?.title ?? `Request failed with status ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.problem = problem;
  }
}

export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${API_URL}/api/v1${path}`, {
    headers: { Accept: "application/json" },
    signal,
  });
  if (!response.ok) {
    const isProblem = response.headers.get("content-type")?.includes("application/problem+json");
    throw new ApiError(response.status, isProblem ? ((await response.json()) as Problem) : null);
  }
  return (await response.json()) as T;
}
