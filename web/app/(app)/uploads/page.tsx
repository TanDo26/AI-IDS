import type { Metadata } from "next";

import { UploadsView } from "./UploadsView";

export const metadata: Metadata = { title: "Uploads" };

export default function UploadsPage() {
  return <UploadsView />;
}
