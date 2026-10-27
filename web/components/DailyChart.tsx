import { Tooltip } from "@/components/Tooltip";
import { type Bucket, MEASURES, type Measure, bucketLabel, niceMax } from "@/lib/usage";

/**
 * One measure per day (or week) as columns: one series, so one colour and no legend. A round top
 * value on the axis, a recessive midline, values on hover, and the same numbers as a table.
 */
export function DailyChart({ buckets, measure }: { buckets: Bucket[]; measure: Measure }) {
  const { label, format } = MEASURES[measure];
  const values = buckets.map((b) => b[measure]);
  if (!values.some((v) => v > 0)) {
    return <p className="py-10 text-center text-sm text-slate-500">Nothing uploaded in this period.</p>;
  }
  const top = niceMax(Math.max(...values));
  const n = buckets.length;
  const ticks = [0, Math.floor((n - 1) / 2), n - 1];

  return (
    <figure className="space-y-2">
      <div className="flex gap-2">
        <div className="flex h-48 w-16 shrink-0 flex-col justify-between text-right text-xs tabular-nums text-slate-500">
          {/* The top is a round number: "5 MB", not "5.0 MB" */}
          <span className="-mt-2">{format(top).replace(/\.0(?=\D|$)/, "")}</span>
          <span className="-mb-2">0</span>
        </div>
        <div className="relative h-48 min-w-0 flex-1">
          <div className="absolute inset-x-0 top-0 border-t border-slate-100" aria-hidden />
          <div className="absolute inset-x-0 top-1/2 border-t border-slate-100" aria-hidden />
          <div className="absolute inset-0 flex items-end gap-[2px] border-b border-viz-baseline">
            {buckets.map((b, i) => (
              <Tooltip key={b.start} value={format(b[measure])} label={bucketLabel(b)}
                       align={i < n / 4 ? "start" : i >= (3 * n) / 4 ? "end" : "center"}
                       className="flex h-full min-w-0 flex-1 items-end justify-center">
                {b[measure] > 0 && (
                  <span className="block min-h-[2px] w-full max-w-6 rounded-t bg-viz-bar"
                        style={{ height: `${(100 * b[measure]) / top}%` }} />
                )}
              </Tooltip>
            ))}
          </div>
        </div>
      </div>
      <div className="relative ml-[4.5rem] h-4 text-xs text-slate-500" aria-hidden>
        {ticks.filter((t, i) => ticks.indexOf(t) === i).map((t) => (
          <span key={t} className={`absolute whitespace-nowrap ${t === 0 ? "left-0" : t === n - 1 ? "right-0" : "-translate-x-1/2"}`}
                style={t !== 0 && t !== n - 1 ? { left: `${((t + 0.5) / n) * 100}%` } : undefined}>
            {bucketLabel({ start: buckets[t].start, end: buckets[t].start })}
          </span>
        ))}
      </div>
      <figcaption className="text-xs text-slate-500">
        {label} per {buckets[0].start === buckets[0].end ? "day" : "week"} (UTC).
      </figcaption>
      <details className="text-sm">
        <summary className="cursor-pointer text-brand-700">Show as a table</summary>
        <table className="mt-2 w-full max-w-sm text-left">
          <thead className="text-xs uppercase tracking-wide text-slate-500">
            <tr><th className="py-1 font-medium">{buckets[0].start === buckets[0].end ? "Day" : "Week"}</th>
              <th className="py-1 text-right font-medium">{label}</th></tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {buckets.map((b) => (
              <tr key={b.start}><td className="py-1">{bucketLabel(b)}</td>
                <td className="py-1 text-right tabular-nums">{format(b[measure])}</td></tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}
