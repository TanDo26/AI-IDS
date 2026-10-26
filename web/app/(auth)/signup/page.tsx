import type { Metadata } from "next";
import { Suspense } from "react";

import { SignupForm } from "./SignupForm";

export const metadata: Metadata = { title: "Create an account" };

export default function SignupPage() {
  return (
    <Suspense>
      <SignupForm />
    </Suspense>
  );
}
