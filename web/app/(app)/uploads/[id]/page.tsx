import type { Metadata } from "next";

import { UploadResultView } from "./UploadResultView";

export const metadata: Metadata = { title: "Upload results" };

export default async function UploadResultPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <UploadResultView id={id} />;
}
