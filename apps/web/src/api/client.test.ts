import { beforeEach, describe, expect, it } from "vitest";

import { json, mockFetch } from "../test/fetchMock";
import { api, ApiError, refreshAccessToken, signOut } from "./client";

beforeEach(async () => {
  mockFetch({ "POST /auth/logout": () => json(null, 204) });
  await signOut();
});

describe("api client", () => {
  it("refreshes once on 401 and retries with the new token", async () => {
    const calls = mockFetch({
      "GET /me": [json({ title: "Unauthorized" }, 401), json({ login: "octo" })],
      "POST /auth/refresh": () => json({ access_token: "fresh-token", expires_in: 900 }),
    });

    const me = await api<{ login: string }>("/me");

    expect(me.login).toBe("octo");
    expect(calls.map((c) => c.key)).toEqual(["GET /me", "POST /auth/refresh", "GET /me"]);
    expect((calls[2]?.init?.headers as Record<string, string>).Authorization).toBe(
      "Bearer fresh-token",
    );
  });

  it("sends the refresh request with cookies", async () => {
    const calls = mockFetch({
      "POST /auth/refresh": () => json({ access_token: "t", expires_in: 900 }),
    });

    await refreshAccessToken();

    expect(calls[0]?.init?.credentials).toBe("include");
  });

  it("shares one refresh between concurrent callers", async () => {
    const calls = mockFetch({
      "POST /auth/refresh": () => json({ access_token: "t", expires_in: 900 }),
    });

    const tokens = await Promise.all([refreshAccessToken(), refreshAccessToken()]);

    expect(tokens).toEqual(["t", "t"]);
    expect(calls).toHaveLength(1);
  });

  it("surfaces problem details as ApiError when refresh fails", async () => {
    mockFetch({
      "GET /me": () =>
        json({ title: "Unauthorized", status: 401, detail: "Not authenticated" }, 401),
      "POST /auth/refresh": () => json({ title: "Unauthorized" }, 401),
    });

    const error = await api("/me").catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(401);
    expect((error as ApiError).message).toBe("Not authenticated");
  });
});
