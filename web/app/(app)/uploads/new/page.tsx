import type { Metadata } from "next";

import { NewUploadView } from "./NewUploadView";

export const metadata: Metadata = { title: "New upload" };

export default function NewUploadPage() {
  return <NewUploadView />;
}
