import type { Metadata } from "next";

import { ModelsView } from "./ModelsView";

export const metadata: Metadata = { title: "Models" };

export default function ModelsPage() {
  return <ModelsView />;
}
