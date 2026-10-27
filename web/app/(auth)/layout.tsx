import Link from "next/link";

// Sign-in and sign-up: a centred card, nothing else on the page
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center px-4 py-12">
      <Link href="/login" className="mb-6 text-2xl font-semibold text-brand-700">AI-IDS</Link>
      <div className="w-full max-w-sm rounded-xl border border-slate-200 bg-white p-8 shadow-sm">{children}</div>
    </main>
  );
}
