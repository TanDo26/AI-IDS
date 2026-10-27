import type { Metadata } from "next";

import { UsageView } from "./UsageView";

export const metadata: Metadata = { title: "Usage" };

/** ?user=<id> opens with that user's chart (the Users page links here). */
export default async function UsagePage({ searchParams }: { searchParams: Promise<{ user?: string }> }) {
  const { user } = await searchParams;
  const id = Number(user);
  const initialUser = Number.isInteger(id) && id > 0 ? id : undefined;
  return <UsageView key={initialUser} initialUser={initialUser} />;
}
