"use client";

import { useRef, useState } from "react";

import { Alert } from "@/components/ui";
import { authErrorMessage } from "@/lib/auth";
import { formatBytes } from "@/lib/format";
import type { Upload } from "@/lib/types";
import { ACCEPTED_TYPES, MAX_UPLOAD_BYTES, checkFile, missingFeatures, uploadFile } from "@/lib/uploads";

type State =
  | { phase: "idle" }
  | { phase: "sending"; file: File; fraction: number }
  | { phase: "failed"; message: string; missing: string[] };

/** Drop or choose one file; it is checked here, sent with progress, and onUploaded gets the queued upload. */
export function UploadDropzone({ onUploaded, disabled = false }:
  { onUploaded: (upload: Upload) => void; disabled?: boolean }) {
  const input = useRef<HTMLInputElement>(null);
  const abort = useRef<AbortController | null>(null);
  const [state, setState] = useState<State>({ phase: "idle" });
  const [dragging, setDragging] = useState(false);
  const busy = state.phase === "sending";

  async function start(file: File | undefined) {
    if (!file || busy || disabled) return;
    const problem = checkFile(file);
    if (problem) {
      setState({ phase: "failed", message: problem, missing: [] });
      return;
    }
    abort.current = new AbortController();
    setState({ phase: "sending", file, fraction: 0 });
    try {
      const upload = await uploadFile(file, {
        signal: abort.current.signal,
        onProgress: (fraction) => setState({ phase: "sending", file, fraction }),
      });
      setState({ phase: "idle" });
      onUploaded(upload);
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") setState({ phase: "idle" });
      else setState({ phase: "failed", message: authErrorMessage(e), missing: missingFeatures(e) });
    } finally {
      if (input.current) input.current.value = "";   // the same file can be chosen again
    }
  }

  return (
    <div className="space-y-3">
      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); start(e.dataTransfer.files[0]); }}
        className={`rounded-xl border-2 border-dashed p-8 text-center transition-colors ${
          disabled ? "border-slate-200 bg-slate-50 opacity-60"
          : dragging ? "border-brand-600 bg-brand-50" : "border-slate-300 bg-white"}`}
      >
        {busy ? (
          <div className="mx-auto max-w-sm space-y-2" aria-live="polite">
            <p className="truncate text-sm font-medium">{state.file.name}</p>
            <div className="h-2 overflow-hidden rounded-full bg-slate-200" role="progressbar"
                 aria-valuenow={Math.round(state.fraction * 100)} aria-valuemin={0} aria-valuemax={100}>
              <div className="h-full bg-brand-600 transition-all" style={{ width: `${state.fraction * 100}%` }} />
            </div>
            <p className="text-xs text-slate-500">
              {state.fraction < 1
                ? `Sending… ${Math.round(state.fraction * 100)}% of ${formatBytes(state.file.size)}`
                : "Checking the file…"}
            </p>
            <button onClick={() => abort.current?.abort()} className="text-xs text-slate-500 hover:underline">Cancel</button>
          </div>
        ) : (
          <>
            <p className="text-sm text-slate-700">
              Drop a CICFlowMeter CSV here, or{" "}
              <button type="button" disabled={disabled} onClick={() => input.current?.click()}
                      className="font-medium text-brand-700 hover:underline disabled:no-underline">choose a file</button>
            </p>
            <p className="mt-1 text-xs text-slate-500">
              One file, up to {formatBytes(MAX_UPLOAD_BYTES)}. The type is read from its content.
            </p>
          </>
        )}
        <input ref={input} type="file" accept={ACCEPTED_TYPES} className="hidden" disabled={disabled}
               aria-label="Choose a file to upload" onChange={(e) => start(e.target.files?.[0])} />
      </div>
      {state.phase === "failed" && (
        <Alert>
          {state.missing.length
            ? `The CSV lacks ${state.missing.length} feature(s) the active model needs.`
            : state.message}
          {state.missing.length > 0 && (
            <span className="mt-2 block max-h-32 overflow-y-auto text-xs">{state.missing.join(", ")}</span>
          )}
        </Alert>
      )}
    </div>
  );
}
