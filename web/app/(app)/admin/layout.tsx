"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { Alert } from "@/components/ui";
import { useMe } from "@/lib/auth";

// Sections are added here as they are built (users, usage, audit)
const TABS = [
  { href: "/admin", label: "Server" },
  { href: "/admin/models", label: "Models" },
];

/** The API refuses non-admins anyway (403); this only saves them a page of errors. */
export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const me = useMe();      // already loaded by the app layout

  if (me.data?.role !== "admin") return <Alert>Only administrators can open this page.</Alert>;
  return (
    <div className="space-y-6">
      <nav className="flex gap-1 border-b border-slate-200" aria-label="Admin sections">
        {TABS.map((tab) => {
          const current = pathname === tab.href;
          return (
            <Link key={tab.href} href={tab.href} aria-current={current ? "page" : undefined}
                  className={`-mb-px border-b-2 px-3 py-2 text-sm ${current
                    ? "border-brand-600 font-medium text-brand-700" : "border-transparent text-slate-600 hover:text-slate-900"}`}>
              {tab.label}
            </Link>
          );
        })}
      </nav>
      {children}
    </div>
  );
}
