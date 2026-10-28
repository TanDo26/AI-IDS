"use client";

import Link from "next/link";
import { useState } from "react";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Pager } from "@/components/Pager";
import { Alert } from "@/components/ui";
import { useMe } from "@/lib/auth";
import { formatDateTime } from "@/lib/format";
import type { AdminUser } from "@/lib/types";
import { type UserAction, type UserQuery, useDebounced, useUpdateUser, useUsers, userActions } from "@/lib/users";

const PAGE_SIZE = 20;
const ROLES: Array<{ label: string; role?: UserQuery["role"] }> = [
  { label: "Everyone" }, { label: "Admins", role: "admin" }, { label: "Users", role: "user" },
];
const STATUSES: Array<{ label: string; active?: boolean }> = [
  { label: "Any status" }, { label: "Active", active: true }, { label: "Deactivated", active: false },
];
const SELECT = "rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm";

export function UsersView() {
  const me = useMe();
  const [search, setSearch] = useState("");
  const [role, setRole] = useState<UserQuery["role"]>();
  const [active, setActive] = useState<boolean>();
  const [page, setPage] = useState(1);
  const q = useDebounced(search);
  const users = useUsers({ q, role, active, page, size: PAGE_SIZE });
  const update = useUpdateUser();
  const [pending, setPending] = useState<{ user: AdminUser; action: UserAction } | null>(null);
  const [notice, setNotice] = useState<string>();

  const cancel = () => { setPending(null); update.reset(); };
  const confirm = () => {
    if (!pending) return;
    update.mutate({ id: pending.user.id, change: pending.action.change }, {
      onSuccess: () => { setNotice(pending.action.done); setPending(null); },
    });
  };

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Users</h1>
      <div className="flex flex-wrap items-center gap-3">
        <input type="search" value={search} placeholder="Search email or username" aria-label="Search users"
               onChange={(e) => { setSearch(e.target.value); setPage(1); }}
               className="w-full max-w-xs rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-brand-600 focus:outline-none focus:ring-1 focus:ring-brand-600" />
        <select aria-label="Role" value={role ?? ""} className={SELECT}
                onChange={(e) => { setRole((e.target.value || undefined) as UserQuery["role"]); setPage(1); }}>
          {ROLES.map((r) => <option key={r.label} value={r.role ?? ""}>{r.label}</option>)}
        </select>
        <select aria-label="Status" value={active === undefined ? "" : String(active)} className={SELECT}
                onChange={(e) => { setActive(e.target.value === "" ? undefined : e.target.value === "true"); setPage(1); }}>
          {STATUSES.map((s) => <option key={s.label} value={s.active === undefined ? "" : String(s.active)}>{s.label}</option>)}
        </select>
      </div>

      {notice && <Alert tone="success">{notice}</Alert>}
      {users.isError && <Alert>{users.error.message}</Alert>}

      <section className="rounded-xl border border-slate-200 bg-white" aria-label="User list">
        {!users.data ? <p className="px-4 py-8 text-center text-sm text-slate-500">Loading…</p>
          : users.data.items.length === 0 ? <p className="px-4 py-8 text-center text-sm text-slate-500">No users match.</p>
          : (
            <div className={`relative overflow-x-auto ${users.isPlaceholderData ? "opacity-60" : ""}`}>
              <table className="w-full text-left text-sm">
                <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="px-4 py-2 font-medium">User</th>
                    <th className="px-4 py-2 font-medium">Role</th>
                    <th className="px-4 py-2 font-medium">Status</th>
                    <th className="px-4 py-2 font-medium">Joined</th>
                    <th className="px-4 py-2 font-medium">Last sign-in</th>
                    <th className="px-4 py-2"><span className="sr-only">Actions</span></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {users.data.items.map((u) => (
                    <Row key={u.id} user={u} actions={userActions(u, me.data?.id ?? -1)}
                         onAction={(action) => { setNotice(undefined); setPending({ user: u, action }); }} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        {users.data && <Pager page={page} size={PAGE_SIZE} total={users.data.total} onPage={setPage} />}
      </section>

      <ConfirmDialog open={pending !== null} title={pending?.action.title ?? ""} confirmLabel={pending?.action.label ?? ""}
                     pending={update.isPending} error={update.error?.message} onConfirm={confirm} onCancel={cancel}>
        <p>{pending?.action.body}</p>
      </ConfirmDialog>
    </div>
  );
}

function Row({ user, actions, onAction }: { user: AdminUser; actions: UserAction[]; onAction: (a: UserAction) => void }) {
  return (
    <tr>
      <td className="px-4 py-2">
        <span className="block font-medium">{user.username}</span>
        <span className="block text-xs text-slate-500">{user.email}</span>
      </td>
      <td className="px-4 py-2">
        <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${user.role === "admin"
          ? "bg-amber-100 text-amber-800" : "bg-slate-100 text-slate-700"}`}>{user.role}</span>
      </td>
      <td className="whitespace-nowrap px-4 py-2">
        <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${user.is_active ? "text-emerald-800" : "text-slate-500"}`}>
          <span className={`h-2 w-2 rounded-full ${user.is_active ? "bg-status-good" : "bg-slate-400"}`} aria-hidden />
          {user.is_active ? "Active" : "Deactivated"}
        </span>
        {user.needs_email_verification && <span className="block text-xs text-amber-800">Email not confirmed</span>}
      </td>
      <td className="whitespace-nowrap px-4 py-2 text-slate-600">{formatDateTime(user.created_at)}</td>
      <td className="whitespace-nowrap px-4 py-2 text-slate-600">{user.last_login_at ? formatDateTime(user.last_login_at) : "Never"}</td>
      <td className="whitespace-nowrap px-4 py-2 text-right">
        <span className="inline-flex items-center gap-3 text-sm">
          <Link href={`/admin/usage?user=${user.id}`} className="text-slate-600 hover:underline">Usage</Link>
          <Link href={`/admin/audit?target_type=user&target_id=${user.id}`} className="text-slate-600 hover:underline">History</Link>
          {actions.length === 0 ? <span className="text-xs text-slate-500">You</span> : actions.map((a) => (
            <button key={a.label} onClick={() => onAction(a)} aria-label={`${a.label}: ${user.username}`}
                    className={`font-medium hover:underline ${a.change.is_active === false ? "text-red-700" : "text-brand-700"}`}>
              {a.label}
            </button>
          ))}
        </span>
      </td>
    </tr>
  );
}
