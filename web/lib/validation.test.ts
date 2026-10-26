import { describe, expect, it } from "vitest";

import { loginSchema, passwordChangeSchema, signupSchema, utf8Bytes } from "@/lib/validation";

function issues(result: { success: boolean; error?: { issues: { path: PropertyKey[]; message: string }[] } }) {
  return Object.fromEntries((result.error?.issues ?? []).map((i) => [i.path.join("."), i.message]));
}

const good = { email: "Alice@Example.com ", username: "alice_01", password: "correct-horse", confirm: "correct-horse" };

describe("signup", () => {
  it("accepts what the API accepts, normalising the email like the API", () => {
    const result = signupSchema.safeParse(good);
    expect(result.success).toBe(true);
    expect(result.data?.email).toBe("alice@example.com");
  });

  it.each([
    [{ email: "not-an-email" }, "email"],
    [{ email: "a@b" }, "email"],                                    // the API wants a dot in the domain
    [{ username: "ab" }, "username"],
    [{ username: "has space" }, "username"],
    [{ username: "x".repeat(65) }, "username"],
    [{ password: "short", confirm: "short" }, "password"],
    [{ password: "é".repeat(37), confirm: "é".repeat(37) }, "password"],   // 37 characters but 74 bytes
    [{ confirm: "different" }, "confirm"],
  ])("rejects %j on %s", (change, field) => {
    expect(Object.keys(issues(signupSchema.safeParse({ ...good, ...change })))).toContain(field);
  });

  it("counts bytes like bcrypt", () => {
    expect(utf8Bytes("é".repeat(36))).toBe(72);
    expect(signupSchema.safeParse({ ...good, password: "é".repeat(36), confirm: "é".repeat(36) }).success).toBe(true);
  });
});

describe("login", () => {
  it("only needs an email and a password", () => {
    expect(loginSchema.safeParse({ email: "a@b.co", password: "x" }).success).toBe(true);
    expect(issues(loginSchema.safeParse({ email: "a@b.co", password: "" }))).toHaveProperty("password");
  });
});

describe("password change", () => {
  const change = { current_password: "old-password", new_password: "new-password", confirm: "new-password" };

  it("accepts a new matching password", () => {
    expect(passwordChangeSchema.safeParse(change).success).toBe(true);
  });

  it.each([
    [{ confirm: "typo" }, "confirm"],
    [{ new_password: "old-password", confirm: "old-password" }, "new_password"],
    [{ new_password: "short", confirm: "short" }, "new_password"],
    [{ current_password: "" }, "current_password"],
  ])("rejects %j on %s", (diff, field) => {
    expect(Object.keys(issues(passwordChangeSchema.safeParse({ ...change, ...diff })))).toContain(field);
  });
});
