import { formatNumber } from "@/lib/format";

/** "21–40 of 75", Previous, Next. Nothing when everything fits on one page. */
export function Pager({ page, size, total, onPage }:
  { page: number; size: number; total: number; onPage: (page: number) => void }) {
  if (total <= size) return null;
  const pages = Math.ceil(total / size);
  const first = (page - 1) * size;
  return (
    <nav className="flex items-center justify-end gap-3 border-t border-slate-200 px-4 py-3 text-sm" aria-label="Pages">
      <span className="mr-auto text-slate-500">
        {formatNumber(first + 1)}–{formatNumber(Math.min(first + size, total))} of {formatNumber(total)}
      </span>
      <button disabled={page <= 1} onClick={() => onPage(page - 1)}
              className="rounded-md px-3 py-1.5 hover:bg-slate-100 disabled:opacity-40">Previous</button>
      <span className="text-slate-600">Page {formatNumber(page)} of {formatNumber(pages)}</span>
      <button disabled={page >= pages} onClick={() => onPage(page + 1)}
              className="rounded-md px-3 py-1.5 hover:bg-slate-100 disabled:opacity-40">Next</button>
    </nav>
  );
}
