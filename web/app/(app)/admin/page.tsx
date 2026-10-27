import type { Metadata } from "next";

import { ServerView } from "./ServerView";

export const metadata: Metadata = { title: "Server status" };

export default function ServerPage() {
  return <ServerView />;
}
