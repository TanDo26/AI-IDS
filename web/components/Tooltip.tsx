import type { CSSProperties, ReactNode } from "react";

const ALIGN = {
  start: "left-0",
  center: "left-1/2 -translate-x-1/2",
  end: "right-0",
};

/**
 * Hover and keyboard-focus tooltip: the value leads, the label follows. Pure CSS, no positioning
 * library. Hidden with display:none, so a closed tooltip never widens the page; near an edge, align
 * it to that edge.
 */
export function Tooltip({ value, label, children, className = "", style, align = "center" }: {
  value: ReactNode; label: ReactNode; children: ReactNode; className?: string; style?: CSSProperties;
  align?: keyof typeof ALIGN;
}) {
  return (
    <span className={`group relative ${className}`} style={style}>
      {children}
      <span role="tooltip"
            className={`pointer-events-none absolute bottom-full z-10 mb-2 hidden whitespace-nowrap rounded-md bg-slate-900 px-2.5 py-1.5 text-xs text-white shadow-lg group-focus-within:block group-hover:block ${ALIGN[align]}`}>
        <span className="block font-semibold">{value}</span>
        <span className="block text-slate-300">{label}</span>
      </span>
    </span>
  );
}
