import { useQuery } from "@tanstack/react-query";

import { apiGet } from "./client";

export interface Readiness {
  status: "ready";
  migration: string | null;
}

export function useReadiness() {
  return useQuery({
    queryKey: ["readiness"],
    queryFn: ({ signal }) => apiGet<Readiness>("/ready", signal),
    refetchInterval: 30_000,
  });
}
