import type { Upload } from "@/lib/types";

const STYLES: Record<Upload["status"], string> = {
  queued: "bg-slate-100 text-slate-700",
  converting: "bg-brand-50 text-brand-700",
  predicting: "bg-brand-50 text-brand-700",
  completed: "bg-emerald-50 text-emerald-800",
  failed: "bg-red-50 text-red-700",
};

const LABELS: Record<Upload["status"], string> = {
  queued: "Queued",
  converting: "Converting",
  predicting: "Analysing",
  completed: "Completed",
  failed: "Failed",
};

/** Status badge; while a job runs, its progress too. */
export function UploadStatus({ upload }: { upload: Pick<Upload, "status" | "progress"> }) {
  const running = upload.status === "converting" || upload.status === "predicting";
  return (
    <span className="inline-flex items-center gap-2">
      <span className={`rounded px-2 py-0.5 text-xs font-medium ${STYLES[upload.status]}`}>
        {LABELS[upload.status]}{running ? ` ${upload.progress}%` : ""}
      </span>
      {running && (
        <span className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-200" aria-hidden>
          <span className="block h-full bg-brand-600 transition-all" style={{ width: `${upload.progress}%` }} />
        </span>
      )}
    </span>
  );
}
