import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { HomePage } from "./HomePage";

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <HomePage />
    </QueryClientProvider>,
  );
}

function jsonResponse(body: unknown, status = 200, contentType = "application/json") {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": contentType } });
}

describe("HomePage", () => {
  it("shows operational status and schema revision when the API is ready", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ status: "ready", migration: "0001" })),
    );

    renderPage();

    expect(await screen.findByText("Operational")).toBeInTheDocument();
    expect(screen.getByText("schema revision 0001")).toBeInTheDocument();
  });

  it("shows the API as unavailable when readiness fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          jsonResponse(
            { type: "about:blank", title: "Service Unavailable", status: 503 },
            503,
            "application/problem+json",
          ),
        ),
    );

    renderPage();

    expect(await screen.findByText("API unavailable")).toBeInTheDocument();
  });

  it("always shows the public-repositories notice", () => {
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})));

    renderPage();

    expect(screen.getByText(/Only public repositories are supported/)).toBeInTheDocument();
  });
});
