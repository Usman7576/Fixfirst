import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import type { Me, Role } from "../api/queries";
import { AuthContext, type AuthStatus } from "../auth/context";
import { json, mockFetch } from "../test/fetchMock";
import { HomePage } from "./HomePage";
import { LoginPage } from "./LoginPage";

function me(role: Role): Me {
  return {
    id: "u1",
    login: "octo",
    name: null,
    avatar_url: null,
    teams: [{ team_id: "t1", team_name: "octo's team", role }],
  };
}

function renderWith(ui: ReactNode, options: { status?: AuthStatus; user?: Me; url?: string }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const auth = { status: options.status ?? "signed_in", me: options.user, signOut: async () => {} };
  return render(
    <QueryClientProvider client={client}>
      <AuthContext value={auth}>
        <MemoryRouter initialEntries={[options.url ?? "/"]}>{ui}</MemoryRouter>
      </AuthContext>
    </QueryClientProvider>,
  );
}

const REPO = {
  id: "r1",
  team_id: "t1",
  github_full_name: "acme/juice-shop",
  default_branch: "main",
  language: "TypeScript",
  last_scanned_at: null,
  latest_scan: null,
};

describe("LoginPage", () => {
  it("explains why the previous sign-in failed", () => {
    renderWith(<LoginPage />, { status: "signed_out", url: "/login?error=invalid_state" });

    expect(screen.getByRole("alert")).toHaveTextContent("expired or was already used");
    expect(screen.getByRole("link", { name: "Sign in with GitHub" })).toHaveAttribute(
      "href",
      expect.stringContaining("/api/v1/auth/github/login"),
    );
  });
});

describe("HomePage", () => {
  it("lists repositories with a Scan button for developers", async () => {
    mockFetch({ "GET /repos?team_id=t1": () => json([REPO]) });

    renderWith(<HomePage />, { user: me("developer") });

    expect(await screen.findByText("acme/juice-shop")).toBeInTheDocument();
    expect(screen.getByText("Never scanned")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Scan" })).toBeEnabled();
    expect(screen.queryByRole("link", { name: "Connect repository" })).not.toBeInTheDocument();
  });

  it("hides the Scan button from viewers", async () => {
    mockFetch({ "GET /repos?team_id=t1": () => json([REPO]) });

    renderWith(<HomePage />, { user: me("viewer") });

    expect(await screen.findByText("acme/juice-shop")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Scan" })).not.toBeInTheDocument();
  });

  it("disables scanning while a scan is in progress", async () => {
    const running = { ...REPO, latest_scan: { id: "s1", status: "running", stage: "starting" } };
    mockFetch({ "GET /repos?team_id=t1": () => json([running]) });

    renderWith(<HomePage />, { user: me("admin") });

    expect(await screen.findByRole("button", { name: "Scanning…" })).toBeDisabled();
    expect(screen.getByRole("link", { name: "Connect repository" })).toBeInTheDocument();
  });

  it("invites admins to connect a first repository", async () => {
    mockFetch({ "GET /repos?team_id=t1": () => json([]) });

    renderWith(<HomePage />, { user: me("admin") });

    expect(await screen.findByText(/No repositories yet/)).toBeInTheDocument();
  });
});
