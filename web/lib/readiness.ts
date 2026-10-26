import { useQuery } from "@tanstack/react-query";

import { ApiError, api } from "@/lib/api";
import type { Readiness } from "@/lib/types";

/** /readyz (database, Redis, active model). It answers 503 with the same body when something is down. */
export function useReadiness() {
  return useQuery({
    queryKey: ["readyz"],
    queryFn: () =>
      api<Readiness>("/readyz").catch((error: unknown) => {
        const body = error instanceof ApiError ? (error.detail as Readiness | undefined) : undefined;
        if (body?.checks) return body;
        throw error;
      }),
    staleTime: 30_000,
  });
}

/** True once we know no model is active (uploads would be refused with 503). */
export function useNoActiveModel(): boolean {
  const ready = useReadiness();
  return ready.data?.checks.model?.ok === false;
}
