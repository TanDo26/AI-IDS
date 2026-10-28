"use client";

import { useEffect, useId, useRef, useState } from "react";

import { ContributionChart } from "@/components/ContributionChart";
import { Alert } from "@/components/ui";
import { percentOf, useExplanation, verdict } from "@/lib/explain";
import { DECISIONS, REASONS, endpoints } from "@/lib/results";
import type { Explanation, Flow } from "@/lib/types";

/**
 * Why one flow got its decision, in a panel from the right. A native modal <dialog>: it traps focus,
 * closes on Escape, and gives focus back to the row that opened it. Clicking outside closes it too.
 */
export function ExplainDrawer({ uploadId, flow, onClose }:
  { uploadId: string; flow: Flow | null; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (flow && !dialog?.open) dialog?.showModal();
    if (!flow && dialog?.open) dialog.close();
  }, [flow]);

  return (
    <dialog ref={ref} aria-labelledby={titleId} onClose={onClose}
            onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
            className="fixed inset-y-0 right-0 left-auto m-0 h-full max-h-none w-full max-w-2xl bg-white shadow-xl backdrop:bg-slate-900/40">
      {flow && <Panel key={flow.row} uploadId={uploadId} flow={flow} titleId={titleId} onClose={onClose} />}
    </dialog>
  );
}

function Panel({ uploadId, flow, titleId, onClose }:
  { uploadId: string; flow: Flow; titleId: string; onClose: () => void }) {
  const explanation = useExplanation(uploadId, flow.row);
  const decision = DECISIONS[flow.decision];
  const ends = endpoints(flow.metadata);

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-start gap-4 border-b border-slate-200 px-5 py-4">
        <div className="min-w-0 flex-1">
          <h2 id={titleId} className="text-lg font-semibold">Flow {flow.row}</h2>
          {ends && <p className="truncate font-mono text-xs text-slate-600">{ends}</p>}
          {flow.metadata.Timestamp && <p className="text-xs text-slate-500">{flow.metadata.Timestamp}</p>}
        </div>
        <button onClick={onClose} aria-label="Close"
                className="rounded-md px-2 py-1 text-xl leading-none text-slate-500 hover:bg-slate-100">×</button>
      </header>

      <div className="flex-1 space-y-5 overflow-y-auto overscroll-contain px-5 py-4">
        <section className="space-y-3">
          <p className="flex flex-wrap items-center gap-2">
            <span className={`inline-flex items-center gap-1.5 rounded px-2 py-0.5 text-xs font-medium ${decision.badge}`}>
              <span className={`h-2 w-2 rounded-full ${decision.swatch}`} aria-hidden />
              {decision.label}
            </span>
            {REASONS[flow.reason] && <span className="text-xs text-slate-500">{REASONS[flow.reason]}</span>}
          </p>
          <p className="text-sm">{verdict(flow)}</p>
          <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            <Fact term="Class" value={flow.class_name} />
            <Fact term="Confidence" value={percentOf(flow.confidence)} />
            <Fact term="Attack score" value={percentOf(flow.attack_score)} hint="1 − probability of benign" />
            <Fact term="Anomaly score" value={flow.anomaly_score.toFixed(3)}
                  hint="Isolation Forest score: higher is more unusual than benign training traffic" />
            {flow.imputed_cells > 0 && (
              <Fact term="Imputed values" value={String(flow.imputed_cells)}
                    hint="Missing or non-numeric feature values, filled in before predicting" />
            )}
          </dl>
        </section>

        <section className="space-y-3" aria-label="What drove this decision">
          <h3 className="text-sm font-medium uppercase tracking-wide text-slate-500">What drove this decision</h3>
          {explanation.isPending && <p className="text-sm text-slate-500">Computing the explanation…</p>}
          {explanation.isError && <Alert>{explanation.error.message}</Alert>}
          {explanation.data && <Attributions explanation={explanation.data} />}
        </section>
      </div>
    </div>
  );
}

function Fact({ term, value, hint }: { term: string; value: string; hint?: string }) {
  return (
    <div title={hint}>
      <dt className="text-xs text-slate-500">{term}</dt>
      <dd className="truncate font-medium tabular-nums">{value}</dd>
    </div>
  );
}

/** One chart, or for a low-confidence flow the two classes the classifier was torn between. */
function Attributions({ explanation }: { explanation: Explanation }) {
  const [shown, setShown] = useState(0);
  const parts = explanation.explanations;
  const torn = parts.length > 1;

  return (
    <div className="space-y-3">
      {explanation.reason === "anomalous" && (
        <p className="text-sm text-slate-600">
          The features that made this flow unusual, and how far each is from typical benign traffic.
        </p>
      )}
      {torn && (
        <>
          <p className="text-sm text-slate-600">The classifier was torn between these classes:</p>
          <div className="flex flex-wrap gap-1" role="tablist" aria-label="Class explained">
            {parts.map((p, i) => (
              <button key={p.class ?? i} role="tab" aria-selected={shown === i} onClick={() => setShown(i)}
                      className={`rounded-md px-3 py-1.5 text-sm ${shown === i
                        ? "bg-brand-50 font-medium text-brand-700" : "text-slate-600 hover:bg-slate-100"}`}>
                {p.class_name} <span className="text-slate-500">{i === 0 ? "(predicted)" : "(runner-up)"}</span>
              </button>
            ))}
          </div>
        </>
      )}
      <ContributionChart attribution={parts[shown]} />
      <p className="text-xs text-slate-500">Model: {explanation.bundle_id}</p>
    </div>
  );
}
