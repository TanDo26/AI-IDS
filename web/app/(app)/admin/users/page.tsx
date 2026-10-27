import type { Metadata } from "next";

import { UsersView } from "./UsersView";

export const metadata: Metadata = { title: "Users" };

export default function UsersPage() {
  return <UsersView />;
}
