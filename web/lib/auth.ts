"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { User } from "@/lib/types";

export const ME_KEY = ["me"] as const;

/** The signed-in user. Role and active status come from the API on every call, never from a cookie. */
export function useMe() {
  return useQuery({ queryKey: ME_KEY, queryFn: () => api<User>("/auth/me"), staleTime: 60_000 });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return async () => {
    try {
      await api("/auth/logout", { method: "POST" });
    } finally {
      queryClient.clear();
      window.location.assign("/login");   // a full load: no data of this user survives in memory
    }
  };
}
