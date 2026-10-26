"use client";

import Link from "next/link";
import { useRef, useState, type ReactNode } from "react";

import { AttackTypeChart } from "@/components/AttackTypeChart";
import { DecisionSummary } from "@/components/DecisionSummary";
import { FlowsTable } from "@/components/FlowsTable";
import { UploadStatus } from "@/components/UploadStatus";
import { Alert } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { formatBytes, formatDateTime, formatDuration } from "@/lib/format";
import { useSummary, useUpload, type FlowQuery } from "@/lib/results";
import type { Decision, Summary, Upload } from "@/lib/types";
import { isActive } from "@/lib/uploads";

const FIRST_PAGE: FlowQuery = { page: 1, size: 50, sort: "row" };

export function UploadResultView({ id }: { id: string }) {
  const upload = useUpload(id);

  if (upload.isPending) return <p className="text-sm text-slate-500">Loading…</p>;
  if (upload.isError) {
    // 422: not an upload id at all; 404: someone else's, deleted, or never existed
    const gone = upload.error instanceof ApiError && [404, 422].includes(upload.error.status);
    return (
      <div className="max-w-xl space-y-4">
        <Alert>{gone ? "This upload doesn't exist or has been deleted." : upload.error.message}</Alert>
        <BackLink />
      </div>
    );
  }

  const u = upload.data;
  return (
    <div className="space-y-6">
      <Header upload={u} />
      {isActive(u.status) && <Progress upload={u} />}
      {u.status === "failed" && <Alert>The analysis failed: {u.error ?? "unknown error"}</Alert>}
      {u.status === "completed" && <Results id={id} />}
    </div>
  );
}

function BackLink() {
  return <Link href="/uploads" className="text-sm font-medium text-brand-700 hover:underline">← All uploads</Link>;
}

function Header({ upload }: { upload: Upload }) {
  return (
    <div className="space-y-2">
      <BackLink />
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="min-w-0 truncate text-2xl font-semibold" title={upload.original_filename}>
          {upload.original_filename}
        </h1>
        <UploadStatus upload={upload} />
      </div>
      <p className="text-sm text-slate-500">
        Uploaded {formatDateTime(upload.created_at)} · {formatBytes(upload.size_bytes)}
        {upload.processing_ms != null && <> · analysed in {formatDuration(upload.processing_ms)}</>}
      </p>
    </div>
  );
}

function Progress({ upload }: { upload: Upload }) {
  const queued = upload.status === "queued";
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-6" aria-live="polite">
      <p className="font-medium">{queued ? "Waiting for a worker…" : `Analysing… ${upload.progress}%`}</p>
      <p className="mt-1 text-sm text-slate-500">The results appear here as soon as every flow is classified.</p>
      {!queued && (
        <div className="mt-4 h-2 overflow-hidden rounded-full bg-slate-200" aria-hidden>
          <div className="h-full bg-brand-600 transition-all" style={{ width: `${upload.progress}%` }} />
        </div>
      )}
    </section>
  );
}

function Results({ id }: { id: string }) {
  const summary = useSummary(id);
  const [query, setQuery] = useState<FlowQuery>(FIRST_PAGE);
  const flowsRef = useRef<HTMLElement>(null);

  if (summary.isPending) return <p className="text-sm text-slate-500">Loading results…</p>;
  if (summary.isError) {
    const gone = summary.error instanceof ApiError && summary.error.status === 410;
    return <Alert tone={gone ? "info" : "error"}>{gone ? "The results of this upload are no longer available." : summary.error.message}</Alert>;
  }

  const s = summary.data;
  const showFlows = (change: Partial<FlowQuery>) => {
    setQuery({ ...FIRST_PAGE, sort: query.sort, ...change });
    flowsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <>
      <DecisionSummary summary={s} onSelect={(decision: Decision) => showFlows({ decision })} />

      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Known attacks by type" className="lg:col-span-2">
          <AttackTypeChart
            breakdown={s.attack_breakdown}
            selected={query.decision === "known_attack" ? query.className : undefined}
            onSelect={(className) => showFlows(query.className === className && query.decision === "known_attack"
              ? {} : { decision: "known_attack", className })}
          />
        </Card>
        <Card title="About this analysis">
          <AnalysisFacts summary={s} />
        </Card>
      </div>

      <section ref={flowsRef} className="scroll-mt-4 rounded-xl border border-slate-200 bg-white" aria-label="Flows">
        <FlowsTable summary={s} query={query} onQueryChange={setQuery} />
      </section>
    </>
  );
}

function Card({ title, className = "", children }: { title: string; className?: string; children: ReactNode }) {
  return (
    <section className={`rounded-xl border border-slate-200 bg-white p-4 ${className}`}>
      <h2 className="mb-3 text-sm font-medium uppercase tracking-wide text-slate-500">{title}</h2>
      {children}
    </section>
  );
}

function AnalysisFacts({ summary }: { summary: Summary }) {
  const m = summary.model;
  const facts: Array<[string, ReactNode, string?]> = [
    ["Model", m.experiment ? `${m.experiment} · ${m.model ?? "?"}` : (m.bundle_id ?? "—"), m.bundle_id ?? undefined],
    ["Inference", formatDuration(summary.inference_ms)],
    ["Total processing", formatDuration(summary.processing_ms)],
  ];
  if (summary.label_agreement !== null) {
    facts.push(["Agrees with Label", `${(100 * summary.label_agreement).toFixed(1)}%`,
                "Attack-vs-benign agreement with the file's Label column (attack names differ between tools)"]);
  }
  return (
    <dl className="space-y-2 text-sm">
      {facts.map(([term, value, hint]) => (
        <div key={term} className="flex justify-between gap-4" title={hint}>
          <dt className="text-slate-500">{term}</dt>
          <dd className="truncate text-right font-medium tabular-nums">{value}</dd>
        </div>
      ))}
    </dl>
  );
}
