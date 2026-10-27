// End-to-end smoke test of a running stack, through Caddy: a new user signs up, uploads real
// flows, reads the results and an explanation, and uploads a packet capture; an admin switches the
// model, the user's next upload uses it, the first upload still explains with its own model, and
// the admin rolls back.
// See README "Browser smoke test" for how to run it; it leaves its user and uploads behind.
import { readFileSync } from "node:fs";

import { type APIResponse, type Page, expect, test } from "@playwright/test";

const CSV = process.env.E2E_FLOWS_CSV ?? "e2e/data/flows.csv";
const CAPTURE = process.env.E2E_CAPTURE ?? "e2e/data/capture.pcap";
const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL ?? "";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "";
const UPLOAD_URL = /\/uploads\/[0-9a-f-]{36}$/;
const ANALYSIS_MS = 5 * 60_000;

// Answers the app expects to get and handles itself: readiness while no model is active, the 404 step
const EXPECTED_FAILURES = [/^\/api\/v1\/readyz$/, /^\/uploads\/nowhere\/at-all$/];

/** Console errors and failed requests of a page, checked at the end. */
function watch(page: Page, problems: string[]) {
  page.on("console", (m) => {
    // Chrome also logs each 4xx/5xx as "Failed to load resource", without the URL: checked below instead
    if (m.type() === "error" && !m.text().startsWith("Failed to load resource")) problems.push(`console: ${m.text()}`);
  });
  page.on("pageerror", (e) => problems.push(`page error: ${e.message}`));
  page.on("response", (r) => {
    if (r.status() >= 400 && !EXPECTED_FAILURES.some((p) => p.test(new URL(r.url()).pathname))) {
      problems.push(`${r.status()} ${r.request().method()} ${new URL(r.url()).pathname}`);
    }
  });
}

async function json(response: Pick<APIResponse, "ok" | "url" | "status" | "json">) {
  expect(response.ok(), `${response.url()} answered ${response.status()}`).toBeTruthy();
  return response.json();
}

/** On /uploads/new: upload a file (the sample flows by default) and wait for its results; returns the upload id. */
async function uploadAndWait(page: Page, file = CSV): Promise<string> {
  await page.getByLabel("Choose a file to upload").setInputFiles(file);
  await page.waitForURL(UPLOAD_URL, { timeout: 60_000 });
  await expect(page.getByRole("heading", { name: "Known attacks by type" })).toBeVisible({ timeout: ANALYSIS_MS });
  return page.url().split("/").pop()!;
}

test("a user's upload, its results and a model switch, end to end", async ({ browser }) => {
  test.skip(!ADMIN_EMAIL || !ADMIN_PASSWORD, "Set E2E_ADMIN_EMAIL and E2E_ADMIN_PASSWORD (an admin made with create_admin.py)");
  const csv = readFileSync(CSV, "utf-8");
  const nFlows = csv.trimEnd().split("\n").length - 1;
  const problems: string[] = [];
  const tag = Math.random().toString(16).slice(2, 8);
  const username = `e2e_${tag}`;
  const password = `${crypto.randomUUID()}aA1!`;

  const user = await (await browser.newContext({ acceptDownloads: true })).newPage();
  const admin = await (await browser.newContext()).newPage();
  watch(user, problems);
  watch(admin, problems);

  await test.step("a deep link without a session goes to sign-in, then on to sign-up", async () => {
    await user.goto("/uploads");
    await expect(user).toHaveURL(/\/login\?next=%2Fuploads$/);
    await user.getByRole("link", { name: "Create one" }).click();
    await expect(user).toHaveURL(/\/signup\?next=%2Fuploads$/);
  });

  await test.step("signing up lands where the user was going", async () => {
    await user.getByLabel("Email").fill(`${username}@example.test`);
    await user.getByLabel("Username").fill(username);
    await user.getByLabel("Password", { exact: true }).fill(password);
    await user.getByLabel("Repeat the password").fill(password);
    await user.getByRole("button", { name: "Create account" }).click();
    await user.waitForURL("**/uploads");
    await expect(user.getByRole("link", { name: username })).toBeVisible();
    await expect(user.getByRole("link", { name: "Admin", exact: true })).toHaveCount(0);
  });

  let first = "";
  let firstModel = "";
  await test.step("an upload is analysed and its summary adds up", async () => {
    await user.getByRole("link", { name: "New upload" }).click();
    await user.waitForURL("**/uploads/new");
    first = await uploadAndWait(user);
    const summary = await json(await user.request.get(`/api/v1/uploads/${first}/summary`));
    firstModel = summary.model.bundle_id;
    expect(summary.n_flows).toBe(nFlows);
    expect(summary.n_benign + summary.n_unknown + summary.n_known_attack).toBe(nFlows);
    await expect(user.getByRole("heading", { name: "flows.csv" })).toBeVisible();
    await expect(user.getByText(summary.model.experiment, { exact: false }).first()).toBeVisible();
  });

  await test.step("the flows table filters, and a flow explains its decision", async () => {
    const flows = user.getByRole("region", { name: "Flows" });
    const counter = flows.locator("nav span.mr-auto");
    await expect(counter).toHaveText(new RegExp(`of ${nFlows.toLocaleString("en-US")}$`));
    await flows.getByRole("tab", { name: /^Known attack/ }).click();
    await expect(flows.locator(".opacity-60")).toHaveCount(0);
    const explain = flows.locator("tbody tr").first().getByRole("button", { name: /^Explain flow/ });
    const row = (await explain.getAttribute("aria-label"))!.replace("Explain flow ", "");
    await explain.click();
    const drawer = user.getByRole("dialog");
    await expect(drawer.getByRole("heading", { name: `Flow ${row}` })).toBeVisible();
    await expect(drawer.locator("figure li").first()).toBeVisible({ timeout: 30_000 });
    await expect(drawer.getByText(/^Known attack: /)).toBeVisible();
    await drawer.getByRole("button", { name: "Close" }).click();
    await expect(drawer).toBeHidden();
  });

  await test.step("the filtered flows download as CSV", async () => {
    const summary = await json(await user.request.get(`/api/v1/uploads/${first}/summary`));
    const download = user.waitForEvent("download");
    await user.getByRole("button", { name: /^Download these flows/ }).click();
    const file = readFileSync((await (await download).path())!, "utf-8");
    expect(file.trimEnd().split("\n").length - 1).toBe(summary.n_known_attack);
  });

  await test.step("the upload is listed as completed", async () => {
    await user.getByRole("link", { name: "Uploads", exact: true }).click();
    const listed = user.getByRole("row").filter({ has: user.getByRole("link", { name: "flows.csv" }) });
    await expect(listed).toHaveCount(1);
    await expect(listed).toContainText("Completed");
  });

  await test.step("a packet capture is turned into flows and analysed", async () => {
    await user.goto("/uploads/new");
    const upload = await uploadAndWait(user, CAPTURE);
    const summary = await json(await user.request.get(`/api/v1/uploads/${upload}/summary`));
    expect(summary.capture.flows).toBe(summary.n_flows);
    expect(summary.n_benign + summary.n_unknown + summary.n_known_attack).toBe(summary.n_flows);
    const n = (value: number) => value.toLocaleString("en-US");
    await expect(user.getByText(`${n(summary.n_flows)} from ${n(summary.capture.packets)} packets`)).toBeVisible();
  });

  let second = "";
  await test.step("an admin sees the server ready and switches the model", async () => {
    await admin.goto("/login");
    await admin.getByLabel("Email").fill(ADMIN_EMAIL);
    await admin.getByLabel("Password").fill(ADMIN_PASSWORD);
    await admin.getByRole("button", { name: "Sign in" }).click();
    await admin.waitForURL("**/dashboard");
    await admin.getByRole("link", { name: "Admin", exact: true }).click();
    await expect(admin.getByRole("heading", { name: "Server status" })).toBeVisible();
    await expect(admin.getByRole("region", { name: "Services" })).not.toContainText("Down");

    await admin.getByRole("link", { name: "Models", exact: true }).click();
    const { versions } = await json(await admin.request.get("/api/v1/admin/models"));
    const other = versions.find((v: { status: string }) => v.status === "available")?.bundle_id;
    if (!other) {
      test.info().annotations.push({ type: "not checked", description: "model switch: the store has one usable bundle" });
      return;
    }
    await admin.getByRole("button", { name: `Activate ${other}` }).click();
    await admin.getByRole("dialog").getByRole("button", { name: "Activate" }).click();
    await expect(admin.locator("p[role=status]").filter({ hasText: `${other} is now active (was ${firstModel})` })).toBeVisible();
    second = other;
  });

  await test.step("the user's next upload uses the new model", async () => {
    if (!second) return;
    await user.goto("/uploads/new");
    const upload = await uploadAndWait(user);
    const summary = await json(await user.request.get(`/api/v1/uploads/${upload}/summary`));
    expect(summary.model.bundle_id).toBe(second);
  });

  await test.step("the first upload still explains with the model that analysed it", async () => {
    if (!second) return;
    await user.goto(`/uploads/${first}`);
    const flows = user.getByRole("region", { name: "Flows" });
    const explain = flows.locator("tbody tr").first().getByRole("button", { name: /^Explain flow/ });
    const row = (await explain.getAttribute("aria-label"))!.replace("Explain flow ", "");
    const answer = user.waitForResponse((r) => r.url().endsWith(`/flows/${row}/explain`));
    await explain.click();
    expect((await json(await answer)).bundle_id).toBe(firstModel);
    await expect(user.getByRole("dialog").locator("figure li").first()).toBeVisible({ timeout: 30_000 });
    await user.getByRole("dialog").getByRole("button", { name: "Close" }).click();
  });

  await test.step("the admin rolls back, and the audit log records both changes", async () => {
    if (!second) return;
    await admin.getByRole("button", { name: "Roll back" }).click();
    await admin.getByRole("dialog").getByRole("button", { name: "Roll back" }).click();
    await expect(admin.locator("p[role=status]").filter({ hasText: `${firstModel} is now active (was ${second})` })).toBeVisible();
    await admin.getByRole("link", { name: "Audit log", exact: true }).click();
    const entries = admin.getByRole("region", { name: "Entries" }).locator("tbody tr");
    await expect(entries.nth(0)).toContainText("Model rolled back");
    await expect(entries.nth(1)).toContainText("Model activated");
  });

  await test.step("the admin finds the user and their usage", async () => {
    await admin.getByRole("link", { name: "Users", exact: true }).click();
    await admin.getByLabel("Search users").fill(username);
    const listed = admin.getByRole("region", { name: "User list" }).locator("tbody tr");
    await expect(listed).toHaveCount(1);
    await listed.getByRole("link", { name: "Usage" }).click();
    const row = admin.getByRole("region", { name: "Per user" }).getByRole("row").filter({ hasText: username });
    await expect(row.locator("td").nth(1)).toHaveText(second ? "3" : "2");
    await expect(admin.getByRole("region", { name: "Daily activity" })).toContainText(username);
  });

  await test.step("an unknown address says so and leads back", async () => {
    const answer = await user.goto("/uploads/nowhere/at-all");
    expect(answer?.status()).toBe(404);
    await expect(user.getByRole("heading", { name: "Page not found" })).toBeVisible();
    await expect(user).toHaveTitle("Page not found · AI-IDS");
    await user.getByRole("link", { name: "Go to the dashboard" }).click();
    await user.waitForURL("**/dashboard");
  });

  await test.step("no page scrolls sideways on a phone", async () => {
    const pages: Array<[Page, string]> = [
      ...["/dashboard", "/uploads", "/uploads/new", `/uploads/${first}`, "/account"].map((p): [Page, string] => [user, p]),
      ...["/admin", "/admin/models", "/admin/users", "/admin/usage", "/admin/audit"].map((p): [Page, string] => [admin, p]),
    ];
    for (const page of [user, admin]) await page.setViewportSize({ width: 375, height: 800 });
    for (const [page, path] of pages) {
      await page.goto(path);
      await page.locator("main h1").first().waitFor();
      await page.waitForLoadState("networkidle");
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow, `${path} is ${overflow}px wider than the screen`).toBeLessThanOrEqual(0);
    }
  });

  await test.step("signing out ends the session", async () => {
    await user.getByRole("button", { name: "Sign out" }).click();
    await user.waitForURL("**/login");
    await user.goto("/dashboard");
    await expect(user).toHaveURL(/\/login\?next=%2Fdashboard$/);
  });

  expect(problems, "console errors or failed requests").toEqual([]);
});
