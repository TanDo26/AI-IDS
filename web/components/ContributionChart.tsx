import { Tooltip } from "@/components/Tooltip";
import { deviation, directions, formatValue, scale, signed } from "@/lib/explain";
import type { Attribution } from "@/lib/types";

/**
 * SHAP contributions as bars diverging from zero, biggest first: right pushes toward the target,
 * left away from it. Colour says which way that is (red: an attack or unusual; blue: benign or
 * typical); the side and the signed value say it too, so colour is never alone.
 */
export function ContributionChart({ attribution }: { attribution: Attribution }) {
  const items = attribution.contributions;
  const { up, down } = directions(attribution);
  const max = Math.max(...items.map((c) => Math.abs(c.contribution)), Number.EPSILON);
  // Room beside the longest bar for its value (xs tabular digits are about 0.45rem)
  const room = `${Math.max(...items.map((c) => signed(c.contribution).length)) * 0.45 + 0.5}rem`;
  const fill = (alarm: boolean) => (alarm ? "bg-viz-alarm" : "bg-viz-normal");

  return (
    <figure className="space-y-2">
      {/* Each side is labelled where its bars grow */}
      <div className="grid gap-x-3 text-xs font-medium text-slate-600 sm:grid-cols-[13rem_1fr]">
        <span className="hidden sm:block" />
        <div className="grid grid-cols-2">
          <span className="flex items-center justify-end gap-1.5 pr-2">
            <span className={`h-2.5 w-2.5 rounded-sm ${fill(down.alarm)}`} aria-hidden />← {down.label}
          </span>
          <span className="flex items-center gap-1.5 pl-2">
            {up.label} →<span className={`h-2.5 w-2.5 rounded-sm ${fill(up.alarm)}`} aria-hidden />
          </span>
        </div>
      </div>

      <ul className="divide-y divide-slate-100">
        {items.map((c) => {
          const positive = c.contribution >= 0;
          const side = positive ? up : down;
          const width = `calc((100% - ${room}) * ${Math.abs(c.contribution) / max})`;
          const away = deviation(c);
          const bar = c.contribution !== 0 && (
            <span className={`block h-3.5 min-w-[2px] ${fill(side.alarm)} ${positive ? "rounded-r" : "rounded-l"}`}
                  style={{ width }} />
          );
          const value = (
            <span className={`whitespace-nowrap text-xs tabular-nums text-slate-700 ${positive ? "ml-1" : "mr-1"}`}>
              {signed(c.contribution)}
            </span>
          );
          return (
            <li key={c.feature}>
              <Tooltip value={signed(c.contribution, 3)} label={`${side.label} · ${c.feature} = ${formatValue(c.value)}`}
                       align="end" className="grid items-center gap-x-3 py-1.5 sm:grid-cols-[13rem_1fr]">
                <span className="min-w-0 text-sm">
                  <span className="block truncate text-slate-800" title={c.feature}>{c.feature}</span>
                  <span className="block truncate text-xs text-slate-500">
                    = {formatValue(c.value)}{c.value == null && " (imputed)"}
                  </span>
                  {away && <span className="block text-xs text-slate-500">{away}</span>}
                </span>
                {/* The zero axis runs between the two halves */}
                <span className="mt-1 grid grid-cols-2 sm:mt-0">
                  <span className="flex h-5 items-center justify-end border-r border-viz-baseline">
                    {!positive && <>{value}{bar}</>}
                  </span>
                  <span className="flex h-5 items-center">{positive && <>{bar}{value}</>}</span>
                </span>
              </Tooltip>
            </li>
          );
        })}
      </ul>

      <figcaption className="text-xs text-slate-500">
        The {items.length} features with the largest effect, in {scale(attribution)}. Starting from the
        model&apos;s average ({signed(attribution.base_value)}), each value moves the output for this flow.
      </figcaption>
    </figure>
  );
}
