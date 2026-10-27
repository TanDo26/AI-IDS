/**
 * Admin user management: the list, and the role and status changes (each audited by the API).
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { AdminUser, UserPage, UserUpdate } from "@/lib/types";

export interface UserQuery {
  q: string;
  role?: "user" | "admin";
  active?: boolean;
  page: number;
  size: number;
}

export function usersPath(query: UserQuery): string {
  const params = new URLSearchParams({ page: String(query.page), size: String(query.size) });
  if (query.q.trim()) params.set("q", query.q.trim());
  if (query.role) params.set("role", query.role);
  if (query.active !== undefined) params.set("active", String(query.active));
  return `/admin/users?${params}`;
}

export interface UserAction {
  label: string;
  change: UserUpdate;
  title: string;
  body: string;
  done: string;                // the notice once it worked
}

/** What an admin can do to a user. Nothing to themself: the API refuses (409), so no button offers it. */
export function userActions(user: AdminUser, myId: number): UserAction[] {
  if (user.id === myId) return [];
  const who = user.username;
  return [
    user.role === "admin"
      ? { label: "Remove admin", change: { role: "user" }, title: `Remove ${who}'s admin role?`,
          body: `${who} keeps their account and uploads, but loses the admin pages.`,
          done: `${who} is no longer an admin.` }
      : { label: "Make admin", change: { role: "admin" }, title: `Make ${who} an admin?`,
          body: `${who} will manage users and models, and see every user's uploads and the audit log.`,
          done: `${who} is now an admin.` },
    user.is_active
      ? { label: "Deactivate", change: { is_active: false }, title: `Deactivate ${who}?`,
          body: `${who} is signed out everywhere at once and can't sign in until reactivated. `
            + "Their uploads and results are kept.",
          done: `${who} is deactivated and signed out.` }
      : { label: "Reactivate", change: { is_active: true }, title: `Reactivate ${who}?`,
          body: `${who} can sign in again.`, done: `${who} can sign in again.` },
  ];
}

export function useUsers(query: UserQuery) {
  return useQuery({
    queryKey: ["admin", "users", query],
    queryFn: () => api<UserPage>(usersPath(query)),
    placeholderData: keepPreviousData,
  });
}

export function useUpdateUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, change }: { id: number; change: UserUpdate }) =>
      api<AdminUser>(`/admin/users/${id}`, { method: "PATCH", json: change }),
    // The audit log and usage list users too
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["admin"] }),
  });
}

/** The value, once it has stopped changing for `ms` (search boxes). */
export function useDebounced<T>(value: T, ms = 300): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return settled;
}
