export const API_URL = (import.meta.env.VITE_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
const BASE = `${API_URL}/api/v1`;

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

// The access token lives only in memory; the refresh token is an httpOnly cookie the
// browser sends to /auth/* and that scripts can never read.
let accessToken: string | null = null;
let refreshing: Promise<string | null> | null = null;

export const loginUrl = `${BASE}/auth/github/login`;

/** Trades the refresh cookie for a new access token. Concurrent callers share one request. */
export function refreshAccessToken(): Promise<string | null> {
  refreshing ??= (async () => {
    try {
      const response = await fetch(`${BASE}/auth/refresh`, {
        method: "POST",
        credentials: "include",
      });
      accessToken = response.ok
        ? ((await response.json()) as { access_token: string }).access_token
        : null;
      return accessToken;
    } catch {
      accessToken = null;
      return null;
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

export async function signOut(): Promise<void> {
  try {
    await fetch(`${BASE}/auth/logout`, { method: "POST", credentials: "include" });
  } finally {
    accessToken = null;
  }
}

async function toApiError(response: Response): Promise<ApiError> {
  const isProblem = response.headers.get("content-type")?.includes("application/problem+json");
  return new ApiError(response.status, isProblem ? ((await response.json()) as Problem) : null);
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, signal } = options;
  const send = (token: string | null) =>
    fetch(`${BASE}${path}`, {
      method,
      signal,
      headers: {
        Accept: "application/json",
        ...(body !== undefined && { "Content-Type": "application/json" }),
        ...(token && { Authorization: `Bearer ${token}` }),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });

  let response = await send(accessToken);
  if (response.status === 401) {
    // Access tokens last 15 minutes; one silent refresh covers expiry mid-session.
    const token = await refreshAccessToken();
    if (token) response = await send(token);
  }
  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
