import { Tooltip } from "@/components/Tooltip";
import { formatNumber } from "@/lib/format";
import { percent } from "@/lib/results";

/** Known attacks per type: one series, so one colour and no legend; the value sits at each bar's tip. */
export function AttackTypeChart({ breakdown, selected, onSelect }:
  { breakdown: Record<string, number>; selected?: string; onSelect?: (className: string) => void }) {
  const rows = Object.entries(breakdown).sort(([a, x], [b, y]) => y - x || a.localeCompare(b));
  if (rows.length === 0) {
    return <p className="py-6 text-center text-sm text-slate-500">No known attacks in this upload.</p>;
  }
  const max = rows[0][1];
  const total = rows.reduce((sum, [, n]) => sum + n, 0);
  // Room at the tip of the longest bar for its value (tabular digits are about 0.55rem at text-sm)
  const room = `${formatNumber(max).length * 0.55 + 0.75}rem`;

  return (
    <ul className="space-y-1">
      {rows.map(([name, count]) => (
        <li key={name}>
          {/* The whole row is the hover (and focus) target; its tooltip stays inside the card */}
          <Tooltip value={`${formatNumber(count)} flows`} label={`${name} · ${percent(count, total)} of known attacks`}
                   align="end" className="block">
            <button type="button" onClick={() => onSelect?.(name)} aria-pressed={selected === name}
                    className={`grid w-full items-center gap-x-3 gap-y-0.5 rounded-md px-2 py-1 text-left text-sm sm:grid-cols-[minmax(8rem,14rem)_1fr] ${
                      selected === name ? "bg-brand-50" : "hover:bg-slate-50"}`}>
              <span className="truncate text-slate-700" title={name}>{name}</span>
              {/* Bars grow from a baseline (on a phone, under their name) */}
              <span className="flex h-4 items-center border-l border-viz-baseline">
                <span className="block h-full min-w-[2px] rounded-r bg-viz-bar"
                      style={{ width: `calc((100% - ${room}) * ${count / max})` }} />
                <span className="ml-2 whitespace-nowrap tabular-nums text-slate-700">{formatNumber(count)}</span>
              </span>
            </button>
          </Tooltip>
        </li>
      ))}
    </ul>
  );
}
