import { describe, expect, it } from "vitest";

import { ACTION_FILTERS, actionLabel, actorName, auditPath, describeDetails } from "@/lib/audit";
import { userActions, usersPath } from "@/lib/users";
import type { AdminUser } from "@/lib/types";

describe("audit", () => {
  it("names actions, keeping unknown ones as they are", () => {
    expect(actionLabel("user.promote")).toBe("Made admin");
    expect(actionLabel("something.new")).toBe("something.new");
    expect(ACTION_FILTERS.slice(0, 3).map((f) => f.value)).toEqual(["", "user.", "model."]);
  });

  it("names the actor", () => {
    expect(actorName({ actor_id: 3, actor_email: "a@x" })).toBe("a@x");
    expect(actorName({ actor_id: null, actor_email: null })).toBe("Command line");
    expect(actorName({ actor_id: 9, actor_email: null })).toBe("Deleted user #9");
  });

  it.each([
    ["user.promote", { email: "b@x", from: "user", to: "admin" }, "b@x: user → admin"],
    ["user.deactivate", { email: "b@x", from: true, to: false }, "b@x"],
    ["user.create_admin", { email: "a@x", via: "scripts/create_admin.py" }, "a@x via scripts/create_admin.py"],
    ["user.purge_unverified", { email: "a@x", username: "al" },
     "a@x (al), never confirmed: its address or username was signed up for again"],
    ["model.activate", { bundle_id: "B-2", previous: "B-1" }, "B-2 (was B-1)"],
    ["model.rollback", { bundle_id: "B-1", previous: null }, "B-1"],
    ["model.rescan", { added: ["B-2", "B-3"], verified: ["B-1", "B-2"], invalid: ["B-3"], retired: [] },
     "2 new, 2 passed, 1 failed, 0 no longer in the store (failed: B-3)"],
    ["upload.delete", { owner_id: 4, filename: "flows.csv" }, "flows.csv (owner #4)"],
    ["something.new", { k: 1 }, '{"k":1}'],
  ])("%s details", (action, details, text) => expect(describeDetails({ action, details })).toBe(text));

  it("builds the query", () => {
    expect(auditPath({ page: 1, size: 50 })).toBe("/admin/audit?page=1&size=50");
    expect(auditPath({ page: 2, size: 50, action: "user.", actorId: 3, target: { type: "user", id: "7" } }))
      .toBe("/admin/audit?page=2&size=50&action=user.&actor_id=3&target_type=user&target_id=7");
  });
});

describe("users", () => {
  const user = (id: number, role: "user" | "admin", is_active: boolean): AdminUser => ({
    id, email: `u${id}@x`, username: `u${id}`, role, is_active, created_at: "2026-10-01T00:00:00Z", last_login_at: null,
    email_verified_at: "2026-10-01T00:00:00Z", needs_email_verification: false });

  it("offers the opposite role and status, and nothing on your own row", () => {
    expect(userActions(user(2, "user", true), 1).map((a) => [a.label, a.change])).toEqual([
      ["Make admin", { role: "admin" }], ["Deactivate", { is_active: false }]]);
    expect(userActions(user(2, "admin", false), 1).map((a) => [a.label, a.change])).toEqual([
      ["Remove admin", { role: "user" }], ["Reactivate", { is_active: true }]]);
    expect(userActions(user(1, "admin", true), 1)).toEqual([]);
    expect(userActions(user(2, "user", true), 1)[1].body).toMatch(/signed out everywhere/);
  });

  it("builds the query, trimming the search", () => {
    expect(usersPath({ q: "  ali ", page: 1, size: 20 })).toBe("/admin/users?page=1&size=20&q=ali");
    expect(usersPath({ q: "", role: "admin", active: false, page: 2, size: 20 }))
      .toBe("/admin/users?page=2&size=20&role=admin&active=false");
  });
});
