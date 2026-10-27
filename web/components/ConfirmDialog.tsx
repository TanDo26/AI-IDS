"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";

import { Alert, Button } from "@/components/ui";

/**
 * Ask before an action that changes what everyone gets. A native modal <dialog>: focus starts on
 * Cancel (the safe choice), Escape cancels. It stays open while the action runs, and shows its error.
 */
export function ConfirmDialog({ open, title, children, confirmLabel, pending = false, error, onConfirm, onCancel }: {
  open: boolean; title: string; children: ReactNode; confirmLabel: string; pending?: boolean; error?: string;
  onConfirm: () => void; onCancel: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (open && !dialog?.open) dialog?.showModal();
    if (!open && dialog?.open) dialog.close();
  }, [open]);

  return (
    <dialog ref={ref} aria-labelledby={titleId} onClose={onCancel}
            className="m-auto w-[calc(100%-2rem)] max-w-md rounded-xl bg-white shadow-xl backdrop:bg-slate-900/40">
      <div className="space-y-4 p-6">
        <h2 id={titleId} className="text-lg font-semibold">{title}</h2>
        <div className="space-y-2 text-sm text-slate-600">{children}</div>
        {error && <Alert>{error}</Alert>}
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onCancel}
                  className="rounded-md px-4 py-2 font-medium text-slate-600 hover:bg-slate-100">Cancel</button>
          <Button type="button" pending={pending} onClick={onConfirm}>{pending ? "Working…" : confirmLabel}</Button>
        </div>
      </div>
    </dialog>
  );
}
