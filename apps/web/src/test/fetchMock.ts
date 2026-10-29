import { vi } from "vitest";

type Route = (init: RequestInit | undefined) => Response | Promise<Response>;

export function json(body: unknown, status = 200): Response {
  const contentType = status >= 400 ? "application/problem+json" : "application/json";
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { "content-type": contentType },
  });
}

/** Stubs fetch with handlers keyed by "METHOD /path" (path relative to /api/v1). */
export function mockFetch(routes: Record<string, Route | Response[]>) {
  const calls: { key: string; init: RequestInit | undefined }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    const key = `${init?.method ?? "GET"} ${url.pathname.replace("/api/v1", "")}${url.search}`;
    calls.push({ key, init });
    const route = routes[key];
    if (Array.isArray(route)) {
      const next = route.shift();
      if (next) return next;
    } else if (route) {
      return route(init);
    }
    throw new Error(`Unexpected fetch: ${key}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}
