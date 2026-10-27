"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { ApiError } from "@/lib/api";
import { useLogout, useMe } from "@/lib/auth";

// An upload's results open from /uploads; admin sections have their own tabs under /admin
const NAV = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/uploads", label: "Uploads" },
  { href: "/admin", label: "Admin", admin: true },
];

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const me = useMe();
  const logout = useLogout();

  if (me.isPending || (me.error instanceof ApiError && me.error.status === 401)) {
    // Loading, or the session is over and the API client is already on its way to /login
    return <div className="p-8 text-sm text-slate-500">Loading…</div>;
  }
  // 403: an admin deactivated the account. Asking again won't help; signing out clears the session.
  const refused = me.error instanceof ApiError && me.error.status === 403;
  const user = me.data;
  // Any other error only takes over before the user is known: a failed background check (e.g. the
  // API restarting) keeps the page, whose own requests say what failed
  if (!user || refused) {
    return (
      <div className="mx-auto max-w-md p-8">
        <p className="mb-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
          {me.error?.message}{refused && ". Ask an administrator to reactivate it."}
        </p>
        <button onClick={refused ? logout : () => me.refetch()} className="text-sm font-medium text-brand-700 hover:underline">
          {refused ? "Sign out" : "Try again"}
        </button>
      </div>
    );
  }

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        {/* On a phone the account links wrap to a second line instead of widening the page */}
        <div className="mx-auto flex min-h-14 max-w-6xl flex-wrap items-center gap-x-6 gap-y-1 px-4 py-2">
          <Link href="/dashboard" className="font-semibold text-brand-700">AI-IDS</Link>
          <nav className="flex gap-1">
            {NAV.filter((item) => !item.admin || user.role === "admin").map((item) => (
              <Link key={item.href} href={item.href}
                    className={`rounded-md px-3 py-1.5 text-sm ${pathname.startsWith(item.href)
                      ? "bg-brand-50 font-medium text-brand-700" : "text-slate-600 hover:bg-slate-100"}`}>
                {item.label}
              </Link>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-3 text-sm">
            <Link href="/account" className={`rounded-md px-2 py-1 ${pathname.startsWith("/account")
              ? "bg-brand-50 font-medium text-brand-700" : "text-slate-600 hover:bg-slate-100"}`}>
              {user.username}
            </Link>
            {user.role === "admin" && (
              <span className="rounded bg-amber-100 px-1.5 py-0.5 text-xs font-medium text-amber-800">admin</span>
            )}
            <button onClick={logout} className="rounded-md px-2 py-1 text-slate-600 hover:bg-slate-100">
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-8">{children}</main>
    </div>
  );
}
