import { Tooltip } from "@/components/Tooltip";
import { formatNumber } from "@/lib/format";
import { DECISIONS, DECISION_ORDER, percent } from "@/lib/results";
import type { Decision, Summary } from "@/lib/types";

/** Benign / unknown / known attack: three tiles (the numbers) over one 100% bar (the proportions). */
export function DecisionSummary({ summary, onSelect }:
  { summary: Summary; onSelect?: (decision: Decision) => void }) {
  const counts: Record<Decision, number> = {
    benign: summary.n_benign, unknown: summary.n_unknown, known_attack: summary.n_known_attack,
  };
  const total = summary.n_flows;
  const unknownWhy = summary.unknown_breakdown;
  const shown = DECISION_ORDER.filter((d) => counts[d] > 0);

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-3">
        {DECISION_ORDER.map((d) => (
          <button key={d} type="button" onClick={() => onSelect?.(d)} title={DECISIONS[d].hint}
                  className="rounded-xl border border-slate-200 bg-white p-4 text-left hover:border-slate-300">
            <span className="flex items-center gap-2 text-sm text-slate-600">
              <span className={`h-2.5 w-2.5 rounded-full ${DECISIONS[d].swatch}`} aria-hidden />
              {DECISIONS[d].label}
            </span>
            <span className="mt-1 block text-3xl font-semibold">{formatNumber(counts[d])}</span>
            <span className="block text-sm text-slate-500">
              {percent(counts[d], total)} of {formatNumber(total)} flows
            </span>
            {d === "unknown" && counts.unknown > 0 && (
              <span className="mt-2 block text-xs text-slate-500">
                {formatNumber(unknownWhy.low_confidence ?? 0)} low confidence ·{" "}
                {formatNumber(unknownWhy.anomalous ?? 0)} anomalous
              </span>
            )}
          </button>
        ))}
      </div>
      {/* Proportions; the tiles above carry the numbers. 2px surface gaps between segments,
          square at the left baseline, rounded at the far end. */}
      <div className="flex h-3 gap-[2px]" aria-hidden>
        {shown.map((d, i) => (
          <Tooltip key={d} value={`${formatNumber(counts[d])} flows`}
                   label={`${DECISIONS[d].label} · ${percent(counts[d], total)}`}
                   align={i === 0 ? "start" : i === shown.length - 1 ? "end" : "center"}
                   className="block h-full min-w-[3px]" style={{ flexGrow: counts[d], flexBasis: 0 }}>
            <span className={`block h-full w-full ${DECISIONS[d].swatch} ${i === shown.length - 1 ? "rounded-r" : ""}`} />
          </Tooltip>
        ))}
      </div>
    </div>
  );
}
