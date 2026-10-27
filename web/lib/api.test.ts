import { afterEach, beforeEach, describe, expect, it, type Mock, vi } from "vitest";

import {
  API_BASE, ApiError, NetworkError, api, apiFetch, defaultSessionExpired, errorMessage, onSessionExpired, readCookie,
} from "@/lib/api";

type Call = { path: string; method: string; headers: Record<string, string>; body?: unknown };
type Reply = { status: number; body?: unknown; headers?: Record<string, string> };

let calls: Call[];
let replies: Array<Reply | ((call: Call) => Reply)>;
let expired: Mock<() => void>;

// What get_current_user answers for a missing, expired or invalid access token
const TOKEN_EXPIRED: Reply = { status: 401, body: { detail: "Access token expired" }, headers: { "WWW-Authenticate": "Bearer" } };

beforeEach(() => {
  calls = [];
  replies = [];
  expired = vi.fn<() => void>();
  onSessionExpired(expired);
  vi.stubGlobal("document", { cookie: "other=1; ids_csrf=tok%3Den; x=y" });
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
    const call: Call = { path: url.slice(API_BASE.length), method: init.method!, headers: init.headers as Record<string, string>, body: init.body };
    calls.push(call);
    const reply = replies.shift() ?? { status: 500 };
    const { status, body, headers } = typeof reply === "function" ? reply(call) : reply;
    return new Response(body === undefined ? null : JSON.stringify(body), { status, headers });
  }));
});

afterEach(() => vi.unstubAllGlobals());

describe("requests", () => {
  it("GETs with the session cookies and no CSRF header", async () => {
    replies.push({ status: 200, body: { id: 1 } });
    expect(await api("/auth/me")).toEqual({ id: 1 });
    expect(calls[0]).toMatchObject({ path: "/auth/me", method: "GET" });
    expect(calls[0].headers["X-CSRF-Token"]).toBeUndefined();
    expect(vi.mocked(fetch).mock.calls[0][1]).toMatchObject({ credentials: "same-origin" });
  });

  it("sends JSON and the CSRF token on unsafe methods", async () => {
    replies.push({ status: 200, body: {} });
    await api("/admin/users/3", { method: "PATCH", json: { role: "admin" } });
    expect(calls[0].method).toBe("PATCH");
    expect(calls[0].headers["X-CSRF-Token"]).toBe("tok=en");        // URL-decoded cookie value
    expect(calls[0].headers["Content-Type"]).toBe("application/json");
    expect(calls[0].body).toBe('{"role":"admin"}');
  });

  it("defaults to POST when there is a body, and returns undefined for 204", async () => {
    replies.push({ status: 204 });
    expect(await api("/auth/logout", { body: new FormData() })).toBeUndefined();
    expect(calls[0].method).toBe("POST");
  });
});

describe("expired access token", () => {
  it("refreshes once and retries", async () => {
    replies.push(TOKEN_EXPIRED, { status: 200 }, { status: 200, body: { ok: true } });
    expect(await api("/uploads")).toEqual({ ok: true });
    expect(calls.map((c) => c.path)).toEqual(["/uploads", "/auth/refresh", "/uploads"]);
    expect(calls[1].headers["X-CSRF-Token"]).toBe("tok=en");
    expect(expired).not.toHaveBeenCalled();
  });

  it("shares one refresh between concurrent requests (a refresh token works once)", async () => {
    let refreshes = 0;
    replies.push(
      TOKEN_EXPIRED, TOKEN_EXPIRED,
      (c) => (c.path === "/auth/refresh" ? (refreshes++, { status: 200 }) : { status: 500 }),
      { status: 200, body: 1 }, { status: 200, body: 2 },
    );
    const results = await Promise.all([api("/a"), api("/b")]);
    expect(refreshes).toBe(1);
    expect(results.sort()).toEqual([1, 2]);
  });

  it("ends the session when the refresh fails", async () => {
    replies.push(TOKEN_EXPIRED, { status: 401, body: { detail: "Session expired; please log in again" } });
    await expect(api("/uploads")).rejects.toMatchObject({ status: 401 });
    expect(expired).toHaveBeenCalledTimes(1);
  });

  it.each(["/auth/login", "/auth/signup", "/auth/refresh", "/auth/logout"])(
    "never refreshes for %s", async (path) => {
      replies.push({ ...TOKEN_EXPIRED, body: { detail: "Incorrect email or password" } });
      await expect(api(path, { method: "POST" })).rejects.toThrow("Incorrect email or password");
      expect(calls).toHaveLength(1);
      expect(expired).not.toHaveBeenCalled();
    });

  it("refreshes for /auth/me", async () => {
    replies.push(TOKEN_EXPIRED, { status: 200 }, { status: 200, body: { id: 1 } });
    await api("/auth/me");
    expect(calls).toHaveLength(3);
  });

  it("returns a 401 without WWW-Authenticate as it is: it answers what the user typed", async () => {
    replies.push({ status: 401, body: { detail: "Current password is incorrect" } });
    await expect(api("/auth/password", { json: {} })).rejects.toThrow("Current password is incorrect");
    expect(calls.map((c) => c.path)).toEqual(["/auth/password"]);   // no refresh, no retry
    expect(expired).not.toHaveBeenCalled();
  });

  it("leaves non-JSON responses to the caller with apiFetch", async () => {
    replies.push({ status: 200, body: "row,decision" });
    const response = await apiFetch("/uploads/x/export.csv");
    expect(response.ok).toBe(true);
  });
});

describe("session expired", () => {
  function stubLocation(pathname: string, search = "") {
    const assign = vi.fn();
    vi.stubGlobal("window", { location: { pathname, search, assign } });
    return assign;
  }

  it("sends the user to /login, remembering the page and saying why", () => {
    const assign = stubLocation("/uploads", "?page=2");
    defaultSessionExpired();
    expect(assign).toHaveBeenCalledWith("/login?next=%2Fuploads%3Fpage%3D2&expired=1");
  });

  it("does nothing on a public page (no redirect loop on /login)", () => {
    const assign = stubLocation("/login");
    defaultSessionExpired();
    expect(assign).not.toHaveBeenCalled();
  });
});

describe("errors", () => {
  it("raises ApiError with the server's message", async () => {
    replies.push({ status: 409, body: { detail: "That email is already registered" } });
    const error = await api("/auth/signup", { json: {} }).catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 409, message: "That email is already registered" });
  });

  it("keeps Retry-After of a 429", async () => {
    replies.push({ status: 429, body: { detail: "Too many requests, try again later." }, headers: { "Retry-After": "42" } });
    await expect(api("/auth/login", { json: {} })).rejects.toMatchObject({ status: 429, retryAfter: 42 });
  });

  it("turns a request without any answer into a NetworkError, but lets a cancel through", async () => {
    replies.push(() => { throw new TypeError("Failed to fetch"); });
    const error = await api("/uploads").catch((e) => e);
    expect(error).toBeInstanceOf(NetworkError);
    expect(error).toMatchObject({ message: "Can't reach the server. Check your connection and try again." });
    replies.push(() => { throw new DOMException("The user aborted a request.", "AbortError"); });
    await expect(api("/uploads")).rejects.toMatchObject({ name: "AbortError" });
  });

  it.each([
    [{ detail: "plain" }, 400, "plain"],
    [{ detail: { message: "2 required feature(s) missing", missing: ["a", "b"] } }, 422, "2 required feature(s) missing"],
    [{ detail: [{ loc: ["body", "email"], msg: "Not a valid email address" }, { loc: ["query", "size"], msg: "too big" }] },
      422, "email: Not a valid email address; query.size: too big"],
    [undefined, 500, "The server had a problem; please try again."],
    [undefined, 502, "The server isn't answering right now; please try again in a moment."],
    [{ detail: "No model is active" }, 503, "No model is active"],
    ["<html>", 404, "Request failed (404)"],
  ])("reads FastAPI error bodies (%j, %i)", (body, status, message) => {
    expect(errorMessage(body, status)).toBe(message);
  });
});

it("reads cookies", () => {
  expect(readCookie("ids_csrf")).toBe("tok=en");
  expect(readCookie("missing")).toBeUndefined();
});
