"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { ApiError } from "@/lib/api";
import { useLogout, useMe } from "@/lib/auth";

// Pages are added here as they are built (results, admin)
const NAV = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/uploads", label: "Uploads" },
];

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const me = useMe();
  const logout = useLogout();

  if (me.isPending || (me.error instanceof ApiError && me.error.status === 401)) {
    // Loading, or the session is over and the API client is already on its way to /login
    return <div className="p-8 text-sm text-slate-500">Loading…</div>;
  }
  if (me.isError) {
    return (
      <div className="mx-auto max-w-md p-8">
        <p className="mb-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{me.error.message}</p>
        <button onClick={() => me.refetch()} className="text-sm font-medium text-brand-700 hover:underline">
          Try again
        </button>
      </div>
    );
  }

  const user = me.data;
  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-6 px-4">
          <Link href="/dashboard" className="font-semibold text-brand-700">AI-IDS</Link>
          <nav className="flex gap-1">
            {NAV.map((item) => (
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
