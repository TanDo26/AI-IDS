import { useId, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type Ref } from "react";

type FieldProps = InputHTMLAttributes<HTMLInputElement> & {
  label: string;
  error?: string;
  hint?: string;
  ref?: Ref<HTMLInputElement>;   // from react-hook-form's register()
};

export function Field({ label, error, hint, ref, ...input }: FieldProps) {
  const id = useId();
  const note = error ?? hint;
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-slate-700">{label}</label>
      <input
        id={id}
        ref={ref}
        aria-invalid={error ? true : undefined}
        aria-describedby={note ? `${id}-note` : undefined}
        className={`mt-1 block w-full rounded-md border px-3 py-2 focus:outline-none focus:ring-1 ${
          error ? "border-red-400 focus:border-red-500 focus:ring-red-500"
                : "border-slate-300 focus:border-brand-600 focus:ring-brand-600"}`}
        {...input}
      />
      {note && (
        <p id={`${id}-note`} className={`mt-1 text-xs ${error ? "text-red-600" : "text-slate-500"}`}>{note}</p>
      )}
    </div>
  );
}

export function Button({ pending, children, className = "", ...props }:
  ButtonHTMLAttributes<HTMLButtonElement> & { pending?: boolean }) {
  return (
    <button
      {...props}
      disabled={pending || props.disabled}
      className={`rounded-md bg-brand-600 px-4 py-2 font-medium text-white hover:bg-brand-700 disabled:opacity-60 ${className}`}
    >
      {children}
    </button>
  );
}

const TONES = {
  error: "bg-red-50 text-red-700",
  success: "bg-emerald-50 text-emerald-800",
  info: "bg-brand-50 text-brand-700",
};

export function Alert({ tone = "error", children }: { tone?: keyof typeof TONES; children: ReactNode }) {
  return (
    <p role={tone === "error" ? "alert" : "status"} className={`rounded-md px-3 py-2 text-sm ${TONES[tone]}`}>
      {children}
    </p>
  );
}
