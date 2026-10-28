import type { Metadata } from "next";
import { Suspense } from "react";

import { VerifyEmail } from "./VerifyEmail";

export const metadata: Metadata = { title: "Confirm your email address" };

export default function VerifyEmailPage() {
  return (
    <Suspense>
      <VerifyEmail />
    </Suspense>
  );
}
