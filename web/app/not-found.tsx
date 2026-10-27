import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "Page not found" };

// Any unknown address. It renders outside the app shell (no session needed), so it offers the way back.
export default function NotFound() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center px-4 py-12">
      <Link href="/dashboard" className="mb-6 text-2xl font-semibold text-brand-700">AI-IDS</Link>
      <div className="w-full max-w-sm space-y-3 rounded-xl border border-slate-200 bg-white p-8 shadow-sm">
        <h1 className="text-xl font-semibold">Page not found</h1>
        <p className="text-sm text-slate-600">There is nothing at this address. It may be mistyped, or the page has moved.</p>
        <Link href="/dashboard" className="inline-block text-sm font-medium text-brand-700 hover:underline">
          Go to the dashboard
        </Link>
      </div>
    </main>
  );
}
