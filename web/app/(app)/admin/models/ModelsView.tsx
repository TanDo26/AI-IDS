"use client";

import { useState } from "react";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Alert, Button } from "@/components/ui";
import {
  METRICS, activationSummary, best, canServe, describeSource, rate, rescanSummary, rollbackTarget, useModelActions,
  useModels,
} from "@/lib/admin";
import { formatDateTime } from "@/lib/format";
import type { Activation, ModelVersion, ModelsOverview } from "@/lib/types";

const STATUS: Record<string, string> = {
  active: "bg-emerald-50 text-emerald-800",
  available: "bg-slate-100 text-slate-700",
  invalid: "bg-red-50 text-red-700",
  retired: "bg-slate-50 text-slate-400",
};

type Pending = { kind: "activate" | "rollback"; version: ModelVersion };

export function ModelsView() {
  const models = useModels();
  const { rescan, activate, rollback } = useModelActions();
  const [confirming, setConfirming] = useState<Pending | null>(null);
  const [notice, setNotice] = useState<{ tone: "success" | "error"; text: string } | null>(null);

  if (models.isPending) return <p className="text-sm text-slate-500">Loading…</p>;
  if (!models.data) return <Alert>{models.error?.message ?? "No answer from the server."}</Alert>;

  const { versions, active } = models.data;
  const current = versions.find((v) => v.status === "active");
  const back = rollbackTarget(versions);
  const action = confirming?.kind === "rollback" ? rollback : activate;

  const switched = { onSuccess: (a: Activation) => { setConfirming(null); setNotice({ tone: "success", text: activationSummary(a) }); } };
  const confirm = () => {
    if (confirming?.kind === "activate") activate.mutate(confirming.version.id, switched);
    else rollback.mutate(undefined, switched);
  };
  const cancel = () => { setConfirming(null); activate.reset(); rollback.reset(); };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Models</h1>
          <p className="mt-1 text-sm text-slate-500">
            Serving <span className="font-mono text-xs text-slate-800">{active ?? "nothing"}</span>
          </p>
        </div>
        <div className="flex gap-2">
          <button disabled={!back} onClick={() => back && setConfirming({ kind: "rollback", version: back })}
                  title={back ? `Back to ${back.bundle_id}` : "No earlier version to go back to"}
                  className="rounded-md border border-slate-300 bg-white px-4 py-2 font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50">
            Roll back
          </button>
          <Button pending={rescan.isPending} title="Register new bundles in model_store/ and re-check the others"
                  onClick={() => {
                    setNotice(null);
                    rescan.mutate(undefined, {
                      onSuccess: (r) => setNotice({ tone: r.invalid.length ? "error" : "success", text: `Rescan: ${rescanSummary(r)}.` }),
                      onError: (e) => setNotice({ tone: "error", text: e.message }),
                    });
                  }}>
            {rescan.isPending ? "Scanning…" : "Rescan"}
          </Button>
        </div>
      </div>

      {notice && <Alert tone={notice.tone}>{notice.text}</Alert>}
      {!active && <Alert tone="info">No model is active, so uploads are refused. Activate one below.</Alert>}

      <section className="rounded-xl border border-slate-200 bg-white" aria-label="Versions">
        {versions.length === 0
          ? <p className="px-4 py-8 text-center text-sm text-slate-500">No bundles registered. Build one, then Rescan.</p>
          : <VersionTable versions={versions} onActivate={(v) => setConfirming({ kind: "activate", version: v })} />}
      </section>

      <Processes overview={models.data} />

      <ConfirmDialog
        open={confirming !== null}
        title={confirming?.kind === "rollback" ? "Roll back the model?" : "Activate this model?"}
        confirmLabel={confirming?.kind === "rollback" ? "Roll back" : "Activate"}
        pending={action.isPending} error={action.error?.message}
        onConfirm={confirm} onCancel={cancel}>
        {confirming && <SwitchDetails target={confirming.version} current={current} />}
      </ConfirmDialog>
    </div>
  );
}

function SwitchDetails({ target, current }: { target: ModelVersion; current?: ModelVersion }) {
  return (
    <>
      <p>
        <span className="font-mono text-xs text-slate-900">{target.bundle_id}</span>
        {current && <> replaces <span className="font-mono text-xs text-slate-900">{current.bundle_id}</span></>}.
      </p>
      <p>{describeSource(target.source)}: macro-F1 {target.metrics.macro_f1?.toFixed(3) ?? "—"}, attack recall{" "}
        {rate(target.metrics.attack_recall)}, benign false alarms {rate(target.metrics.benign_fpr)}.</p>
      {target.activated_at && <p>It was last activated {formatDateTime(target.activated_at)}.</p>}
      <p>New uploads use it at once. An upload already being analysed finishes with its model, and existing results
        keep the model that produced them.</p>
    </>
  );
}

function VersionTable({ versions, onActivate }: { versions: ModelVersion[]; onActivate: (v: ModelVersion) => void }) {
  const bests = METRICS.map((m) => best(versions, m));
  return (
    // relative: the sr-only labels are absolutely positioned, and would otherwise escape the scroller
    // and widen the whole page on a phone
    <div className="relative overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-slate-200 text-xs text-slate-500">
          <tr>
            <th className="px-3 py-2 font-medium uppercase tracking-wide">Version</th>
            <th className="px-3 py-2 font-medium uppercase tracking-wide">Status</th>
            {METRICS.map((m) => (
              <th key={m.key} title={m.hint} className="px-3 py-2 text-right font-medium">{m.label}</th>
            ))}
            <th className="px-3 py-2"><span className="sr-only">Action</span></th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {versions.map((v) => (
            <tr key={v.id} className={v.status === "active" ? "bg-emerald-50/40" : ""}>
              <td className="min-w-[15rem] px-3 py-2 align-top">
                <span className="block font-mono text-xs font-medium text-slate-900">{v.bundle_id}</span>
                <span className="block text-xs text-slate-600">{describeSource(v.source)}</span>
                <span className="block text-xs text-slate-500">
                  {v.n_features ?? "?"} features · {v.classes.length} classes · registered {formatDateTime(v.registered_at)}
                </span>
              </td>
              <td className="px-3 py-2 align-top">
                <span className={`rounded px-2 py-0.5 text-xs font-medium ${STATUS[v.status] ?? STATUS.available}`}>{v.status}</span>
                {v.invalid_reason && (
                  <span className="mt-1 line-clamp-3 max-w-[14rem] text-xs text-red-700" title={v.invalid_reason}>
                    {v.invalid_reason}
                  </span>
                )}
              </td>
              {METRICS.map((m, i) => {
                const text = m.format(v.metrics[m.key]);
                const isBest = text === bests[i] && canServe(v);
                return (
                  <td key={m.key} className={`whitespace-nowrap px-3 py-2 text-right align-top tabular-nums ${
                    isBest ? "font-semibold text-slate-900" : "text-slate-600"}`}>
                    {text}{isBest && <span className="sr-only"> (best)</span>}
                  </td>
                );
              })}
              <td className="px-3 py-2 text-right align-top">
                {v.status === "available" && (
                  <button onClick={() => onActivate(v)} aria-label={`Activate ${v.bundle_id}`}
                          className="text-sm font-medium text-brand-700 hover:underline">Activate</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="border-t border-slate-200 px-3 py-2 text-xs text-slate-500">
        From each bundle&apos;s test split when it was built. Bold: the best value among the versions that can serve.
      </p>
    </div>
  );
}

/** Which version each API and worker process has in memory, from their reports in Redis. */
function Processes({ overview }: { overview: ModelsOverview }) {
  const { processes, this_process: self } = overview;
  return (
    <section className="rounded-xl border border-slate-200 bg-white" aria-label="Processes">
      <h2 className="border-b border-slate-200 px-4 py-3 text-sm font-medium uppercase tracking-wide text-slate-500">
        Loaded by each process
      </h2>
      {self.last_error && <div className="p-4"><Alert>This API process failed to load a bundle: {self.last_error}</Alert></div>}
      {processes == null ? (
        <p className="px-4 py-6 text-sm text-slate-500">
          Per-process reports need Redis, which isn&apos;t reachable. This API process serves{" "}
          <span className="font-mono text-xs">{self.loaded ?? "nothing"}</span>.
        </p>
      ) : processes.length === 0 ? (
        <p className="px-4 py-6 text-sm text-slate-500">No process has reported yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-2 font-medium">Process</th>
                <th className="px-4 py-2 font-medium">Kind</th>
                <th className="px-4 py-2 font-medium">Loaded</th>
                <th className="px-4 py-2 font-medium">Since</th>
                <th className="px-4 py-2 font-medium">Last report</th>
                <th className="px-4 py-2 font-medium">State</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {processes.map((p) => (
                <tr key={p.process}>
                  <td className="whitespace-nowrap px-4 py-2 font-mono text-xs">{p.process}</td>
                  <td className="px-4 py-2">{p.kind}</td>
                  <td className="whitespace-nowrap px-4 py-2 font-mono text-xs">{p.loaded ?? "nothing"}</td>
                  <td className="whitespace-nowrap px-4 py-2 text-slate-600">{formatDateTime(p.loaded_at)}</td>
                  <td className="whitespace-nowrap px-4 py-2 text-slate-600">{formatDateTime(p.reported_at)}</td>
                  <td className="whitespace-nowrap px-4 py-2">
                    <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${p.lagging ? "text-amber-900" : "text-emerald-800"}`}>
                      <span className={`h-2 w-2 rounded-full ${p.lagging ? "bg-status-warning" : "bg-status-good"}`} aria-hidden />
                      {p.lagging ? "Lagging" : "Current"}
                    </span>
                    {p.last_error && <span className="block text-xs text-red-700">{p.last_error}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="border-t border-slate-200 px-4 py-2 text-xs text-slate-500">
            API processes switch as soon as a model is activated. Workers re-check on a timer
            (<code>IDS_MODEL_POLL_SECONDS</code>), and also whenever a job starts, so no upload is analysed with an
            older model while they show Lagging.
          </p>
        </div>
      )}
    </section>
  );
}
