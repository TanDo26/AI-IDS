import type { Metadata } from "next";

import { AuditView } from "./AuditView";

export const metadata: Metadata = { title: "Audit log" };

/** ?target_type=user&target_id=7 opens on one target's history (the Users page links here). */
export default async function AuditPage({ searchParams }:
  { searchParams: Promise<{ target_type?: string; target_id?: string }> }) {
  const { target_type: type, target_id: id } = await searchParams;
  return <AuditView key={`${type}:${id}`} initialTarget={type && id ? { type, id } : undefined} />;
}
