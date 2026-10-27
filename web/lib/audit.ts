/**
 * The audit log: who changed which user, model or upload, in plain words.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { AuditEntry, AuditPage } from "@/lib/types";

// Every action the API writes (src/api/admin/service.py, runtime/model_registry.py, uploads/service.py,
// scripts/create_admin.py)
export const ACTIONS: Record<string, string> = {
  "user.create_admin": "Admin account created",
  "user.promote": "Made admin",
  "user.demote": "Admin role removed",
  "user.deactivate": "Deactivated",
  "user.reactivate": "Reactivated",
  "model.activate": "Model activated",
  "model.rollback": "Model rolled back",
  "model.rescan": "Model store rescanned",
  "upload.delete": "Upload deleted by an admin",
};

/** The filter's choices: everything, a family (trailing dot: the API matches the prefix), or one action. */
export const ACTION_FILTERS: Array<{ value: string; label: string }> = [
  { value: "", label: "All actions" },
  { value: "user.", label: "All user changes" },
  { value: "model.", label: "All model changes" },
  ...Object.entries(ACTIONS).map(([value, label]) => ({ value, label })),
];

export const actionLabel = (action: string) => ACTIONS[action] ?? action;

export function actorName(entry: Pick<AuditEntry, "actor_id" | "actor_email">): string {
  if (entry.actor_email) return entry.actor_email;
  return entry.actor_id == null ? "Command line" : `Deleted user #${entry.actor_id}`;
}

const list = (value: unknown) => (Array.isArray(value) ? (value as string[]) : []);

/** The details that matter for each action, in a line. */
export function describeDetails(entry: Pick<AuditEntry, "action" | "details">): string {
  const d = entry.details as Record<string, unknown>;
  switch (entry.action) {
    case "user.promote":
    case "user.demote":
      return `${d.email}: ${d.from} → ${d.to}`;
    case "user.deactivate":
    case "user.reactivate":
      return String(d.email ?? "");
    case "user.create_admin":
      return `${d.email}${d.via ? ` via ${d.via}` : ""}`;
    case "model.activate":
    case "model.rollback":
      return `${d.bundle_id}${d.previous ? ` (was ${d.previous})` : ""}`;
    case "model.rescan": {
      const [added, invalid, retired] = [list(d.added), list(d.invalid), list(d.retired)];
      return [`${added.length} new`, `${list(d.verified).length} passed`, `${invalid.length} failed`,
              `${retired.length} no longer in the store`].join(", ")
        + (invalid.length ? ` (failed: ${invalid.join(", ")})` : "");
    }
    case "upload.delete":
      return `${d.filename} (owner #${d.owner_id})`;
    default:
      return Object.keys(d).length ? JSON.stringify(d) : "";
  }
}

export interface AuditQuery {
  page: number;
  size: number;
  action?: string;
  actorId?: number;
  target?: { type: string; id: string };
}

export function auditPath(q: AuditQuery): string {
  const params = new URLSearchParams({ page: String(q.page), size: String(q.size) });
  if (q.action) params.set("action", q.action);
  if (q.actorId !== undefined) params.set("actor_id", String(q.actorId));
  if (q.target) {
    params.set("target_type", q.target.type);
    params.set("target_id", q.target.id);
  }
  return `/admin/audit?${params}`;
}

export function useAudit(q: AuditQuery) {
  return useQuery({
    queryKey: ["admin", "audit", q],
    queryFn: () => api<AuditPage>(auditPath(q)),
    placeholderData: keepPreviousData,
  });
}
