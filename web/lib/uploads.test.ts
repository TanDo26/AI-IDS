import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, onSessionExpired } from "@/lib/api";
import { formatBytes, formatDuration, formatNumber } from "@/lib/format";
import { MAX_UPLOAD_BYTES, checkFile, missingFeatures, uploadFile } from "@/lib/uploads";

// A stand-in for the browser's XMLHttpRequest: each send() answers with the next queued reply
type Reply = { status: number; body?: unknown; headers?: Record<string, string> };
let replies: Reply[];
let sent: Array<{ url: string; headers: Record<string, string>; body: unknown }>;

class FakeXHR {
  upload: { onprogress?: (e: { lengthComputable: boolean; loaded: number; total: number }) => void } = {};
  onload?: () => void;
  onerror?: () => void;
  onabort?: () => void;
  status = 0;
  responseText = "";
  private url = "";
  private headers: Record<string, string> = {};
  private replyHeaders: Record<string, string> = {};
  open(_method: string, url: string) { this.url = url; }
  setRequestHeader(name: string, value: string) { this.headers[name] = value; }
  getResponseHeader(name: string) { return this.replyHeaders[name] ?? null; }
  abort() { this.onabort?.(); }
  send(body: unknown) {
    sent.push({ url: this.url, headers: this.headers, body });
    const reply = replies.shift()!;
    this.upload.onprogress?.({ lengthComputable: true, loaded: 50, total: 100 });
    this.upload.onprogress?.({ lengthComputable: true, loaded: 100, total: 100 });
    this.status = reply.status;
    this.responseText = reply.body === undefined ? "" : JSON.stringify(reply.body);
    this.replyHeaders = reply.headers ?? {};
    queueMicrotask(() => this.onload?.());
  }
}

let fetchReplies: Reply[];
let expired: ReturnType<typeof vi.fn>;

beforeEach(() => {
  replies = [];
  sent = [];
  fetchReplies = [];
  expired = vi.fn();
  onSessionExpired(expired as () => void);
  vi.stubGlobal("XMLHttpRequest", FakeXHR);
  vi.stubGlobal("document", { cookie: "ids_csrf=tok" });
  // fetch serves /auth/me (the pre-flight) and /auth/refresh
  vi.stubGlobal("fetch", vi.fn(async () => {
    const r = fetchReplies.shift() ?? { status: 200, body: { id: 1 } };
    return new Response(r.body === undefined ? null : JSON.stringify(r.body), { status: r.status, headers: r.headers });
  }));
});

afterEach(() => vi.unstubAllGlobals());

const file = (size: number, name = "flows.csv") => new File([new Uint8Array(size)], name);

describe("checkFile", () => {
  it.each([
    [0, "The file is empty."],
    [MAX_UPLOAD_BYTES, null],
    [MAX_UPLOAD_BYTES + 1, "This file is over the 100 MB upload limit (100.0 MB)."],
    [150_000_000, "This file is over the 100 MB upload limit (150.0 MB)."],
  ])("%i bytes -> %s", (size, message) => {
    expect(checkFile({ size } as File)).toBe(message);
  });
});

describe("uploadFile", () => {
  it("sends the file as multipart field 'file' with the CSRF token and reports progress", async () => {
    replies.push({ status: 201, body: { id: "u1", status: "queued" } });
    const progress: number[] = [];
    const upload = await uploadFile(file(10), { onProgress: (f) => progress.push(f) });
    expect(upload).toMatchObject({ id: "u1", status: "queued" });
    expect(sent[0].url).toBe("/api/v1/uploads");
    expect(sent[0].headers["X-CSRF-Token"]).toBe("tok");
    expect((sent[0].body as FormData).get("file")).toBeInstanceOf(File);
    expect(progress).toEqual([0.5, 1]);
  });

  it("refreshes an expired session and sends again", async () => {
    replies.push({ status: 401, body: { detail: "Access token expired" }, headers: { "WWW-Authenticate": "Bearer" } },
                 { status: 201, body: { id: "u2" } });
    fetchReplies.push({ status: 200, body: {} }, { status: 200 });          // /auth/me, then /auth/refresh
    expect(await uploadFile(file(10))).toMatchObject({ id: "u2" });
    expect(sent).toHaveLength(2);
    expect(expired).not.toHaveBeenCalled();
  });

  it("ends the session when the refresh fails", async () => {
    replies.push({ status: 401, body: { detail: "Access token expired" }, headers: { "WWW-Authenticate": "Bearer" } });
    fetchReplies.push({ status: 200, body: {} }, { status: 401 });
    await expect(uploadFile(file(10))).rejects.toMatchObject({ status: 401 });
    expect(expired).toHaveBeenCalledTimes(1);
  });

  it("turns the API's refusals into ApiError, keeping the missing features", async () => {
    const detail = { message: "2 required feature(s) missing: Flow Duration, Flow Bytes/s",
                     missing: ["Flow Duration", "Flow Bytes/s"] };
    replies.push({ status: 422, body: { detail } });
    const error = await uploadFile(file(10)).catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 422, message: detail.message });
    expect(missingFeatures(error)).toEqual(["Flow Duration", "Flow Bytes/s"]);
    expect(missingFeatures(new ApiError(415, "Unsupported file type"))).toEqual([]);
  });

  it("keeps Retry-After of a 429", async () => {
    replies.push({ status: 429, body: { detail: "Too many requests, try again later." }, headers: { "Retry-After": "30" } });
    await expect(uploadFile(file(10))).rejects.toMatchObject({ status: 429, retryAfter: 30 });
  });
});

describe("format", () => {
  it.each([[0, "0 B"], [999, "999 B"], [1500, "1.5 kB"], [100_000_000, "100 MB"], [2_345_000_000, "2.3 GB"]])(
    "bytes %i -> %s", (n, text) => expect(formatBytes(n)).toBe(text));
  it.each([[176, "176 ms"], [4_300, "4.3 s"], [42_000, "42 s"], [125_000, "2 min 5 s"]])(
    "duration %i -> %s", (ms, text) => expect(formatDuration(ms)).toBe(text));
  it("numbers and gaps", () => {
    expect(formatNumber(1234567)).toBe("1,234,567");
    expect(formatBytes(null)).toBe("—");
    expect(formatDuration(undefined)).toBe("—");
  });
});
