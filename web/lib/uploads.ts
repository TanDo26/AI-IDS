/**
 * Uploads: checks before sending, the upload itself (XMLHttpRequest, because fetch can't report
 * upload progress), and the queries the pages share.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { API_BASE, ApiError, api, errorMessage, expireSession, readCookie, refreshSession } from "@/lib/api";
import { CSRF_COOKIE, CSRF_HEADER } from "@/lib/session";
import type { Upload, UploadPage, UploadStatus, UploadTotals } from "@/lib/types";

// The API's IDS_MAX_UPLOAD_MB (decimal MB) and Caddy's cap; checked here so nothing larger is sent
export const MAX_UPLOAD_BYTES = 100_000_000;
export const ACCEPTED_TYPES = ".csv,.pcap,.pcapng";
const ACTIVE: UploadStatus[] = ["queued", "converting", "predicting"];

export const isActive = (status: UploadStatus) => ACTIVE.includes(status);

/** Why this file can't be sent, or null. The type is decided by the server from the content. */
export function checkFile(file: File): string | null {
  if (file.size === 0) return "The file is empty.";
  if (file.size > MAX_UPLOAD_BYTES) {
    return `This file is over the ${MAX_UPLOAD_BYTES / 1e6} MB upload limit (${(file.size / 1e6).toFixed(1)} MB).`;
  }
  return null;
}

/** The features a CSV lacked (422 from the API), if that is why it was refused. */
export function missingFeatures(error: unknown): string[] {
  const detail = error instanceof ApiError ? (error.detail as { detail?: { missing?: unknown } })?.detail : undefined;
  return Array.isArray(detail?.missing) ? (detail.missing as string[]) : [];
}

interface Sent {
  status: number;
  body: unknown;
  asksForAuth: boolean;
  retryAfter?: number;
}

function send(file: File, onProgress?: (fraction: number) => void, signal?: AbortSignal): Promise<Sent> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/uploads`);
    xhr.setRequestHeader("Accept", "application/json");
    const token = readCookie(CSRF_COOKIE);
    if (token) xhr.setRequestHeader(CSRF_HEADER, token);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress?.(e.loaded / e.total);
    };
    xhr.onload = () => {
      let body: unknown = xhr.responseText;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* not JSON: keep the text */
      }
      resolve({
        status: xhr.status,
        body,
        asksForAuth: xhr.status === 401 && Boolean(xhr.getResponseHeader("WWW-Authenticate")),
        retryAfter: Number(xhr.getResponseHeader("Retry-After")) || undefined,
      });
    };
    xhr.onerror = () => reject(new ApiError(0, "The upload was interrupted. Check your connection and try again."));
    xhr.onabort = () => reject(new DOMException("Upload cancelled", "AbortError"));
    signal?.addEventListener("abort", () => xhr.abort(), { once: true });
    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}

/** Send one file; resolves with the queued upload, rejects with ApiError (or AbortError). */
export async function uploadFile(
  file: File,
  { onProgress, signal }: { onProgress?: (fraction: number) => void; signal?: AbortSignal } = {},
): Promise<Upload> {
  // Refresh an expired access token before sending megabytes that would only be refused
  await api("/auth/me");
  let result = await send(file, onProgress, signal);
  if (result.asksForAuth) {
    if (!(await refreshSession())) {
      expireSession();
    } else {
      onProgress?.(0);
      result = await send(file, onProgress, signal);
    }
  }
  if (result.status < 200 || result.status >= 300) {
    throw new ApiError(result.status, errorMessage(result.body, result.status), result.body, result.retryAfter);
  }
  return result.body as Upload;
}

// ── queries ──

const refetchWhileProcessing = (items: Upload[] | undefined) =>
  items?.some((u) => isActive(u.status)) ? 2000 : false;

export function useUploads(page: number, size: number, status?: UploadStatus) {
  return useQuery({
    queryKey: ["uploads", { page, size, status }],
    queryFn: () => {
      const params = new URLSearchParams({ page: String(page), size: String(size) });
      if (status) params.set("status", status);
      return api<UploadPage>(`/uploads?${params}`);
    },
    placeholderData: keepPreviousData,
    refetchInterval: (query) => refetchWhileProcessing(query.state.data?.items),
  });
}

export function useUploadStats(refreshing: boolean) {
  return useQuery({
    queryKey: ["uploads", "stats"],
    queryFn: () => api<UploadTotals>("/uploads/stats"),
    refetchInterval: refreshing ? 2000 : false,
  });
}

/** After an upload or a deletion, every upload query is stale. */
export function useInvalidateUploads() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: ["uploads"] });
}

export function useDeleteUpload() {
  const invalidate = useInvalidateUploads();
  return useMutation({
    mutationFn: (id: string) => api(`/uploads/${id}`, { method: "DELETE" }),
    onSettled: invalidate,
  });
}
