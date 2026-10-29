import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";

export type Role = "admin" | "developer" | "viewer";
export type ScanStatus = "queued" | "running" | "waiting_quota" | "done" | "failed" | "cancelled";

export interface Me {
  id: string;
  login: string;
  name: string | null;
  avatar_url: string | null;
  teams: { team_id: string; team_name: string; role: Role }[];
}

export interface ScanSummary {
  id: string;
  status: ScanStatus;
  stage: string | null;
  created_at: string;
  finished_at: string | null;
  raw_count: number;
  issue_count: number;
  fix_now_count: number;
}

export interface Repo {
  id: string;
  team_id: string;
  github_full_name: string;
  default_branch: string;
  language: string | null;
  last_scanned_at: string | null;
  latest_scan: ScanSummary | null;
}

export interface AvailableRepo {
  github_repo_id: number;
  full_name: string;
  private: boolean;
  language: string | null;
  html_url: string;
  connectable: boolean;
}

export const ACTIVE_STATUSES: ScanStatus[] = ["queued", "running", "waiting_quota"];

export function useMe(enabled: boolean) {
  return useQuery({
    queryKey: ["me"],
    queryFn: ({ signal }) => api<Me>("/me", { signal }),
    enabled,
  });
}

export function useRepos(teamId: string | undefined) {
  return useQuery({
    queryKey: ["repos", teamId],
    queryFn: ({ signal }) => api<Repo[]>(`/repos?team_id=${teamId}`, { signal }),
    enabled: Boolean(teamId),
    // Poll only while a scan is in flight (ADR 0006).
    refetchInterval: (query) =>
      query.state.data?.some((r) => r.latest_scan && ACTIVE_STATUSES.includes(r.latest_scan.status))
        ? 2_000
        : false,
  });
}

export function useAvailableRepos() {
  return useQuery({
    queryKey: ["repos", "available"],
    queryFn: ({ signal }) => api<AvailableRepo[]>("/repos/available", { signal }),
    staleTime: 5 * 60_000,
  });
}

export function useConnectRepo(teamId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (fullName: string) =>
      api<Repo>("/repos", {
        method: "POST",
        body: { team_id: teamId, github_full_name: fullName },
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["repos", teamId] }),
  });
}

export function useStartScan(teamId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (repoId: string) => api<ScanSummary>(`/repos/${repoId}/scans`, { method: "POST" }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["repos", teamId] }),
  });
}
