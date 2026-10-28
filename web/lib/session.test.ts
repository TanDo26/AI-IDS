import { describe, expect, it } from "vitest";

import { nextPath, sessionRedirect } from "@/lib/session";

describe("sessionRedirect (proxy.ts)", () => {
  it.each([
    ["/dashboard", "", false, "/login?next=%2Fdashboard"],
    ["/uploads/42", "?tab=flows", false, "/login?next=%2Fuploads%2F42%3Ftab%3Dflows"],
    ["/", "", false, "/login"],
    ["/dashboard", "", true, null],
    ["/login", "", false, null],
    ["/signup", "", false, null],
    ["/verify-email", "?token=abc", false, null],        // the link may open where nobody is signed in
    ["/healthz", "", false, null],
    ["/loginx", "", false, "/login?next=%2Floginx"],     // only the exact public pages
  ])("%s%s with session=%s -> %s", (path, search, session, expected) => {
    expect(sessionRedirect(path, search, session)).toBe(expected);
  });
});

describe("nextPath (after sign-in)", () => {
  it.each([
    [null, "/dashboard"],
    ["/uploads/42?tab=flows", "/uploads/42?tab=flows"],
    ["https://evil.example/x", "/dashboard"],               // never off-site
    ["//evil.example/x", "/dashboard"],
    ["/\\evil.example", "/dashboard"],
    ["/login", "/dashboard"],                               // not back to a public page
  ])("%s -> %s", (raw, expected) => {
    expect(nextPath(raw)).toBe(expected);
  });
});
