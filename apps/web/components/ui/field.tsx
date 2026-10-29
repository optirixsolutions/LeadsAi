import { clsx } from "clsx";
import { useId } from "react";

const CONTROL =
  "h-9 w-full rounded-md border bg-canvas px-3 text-sm text-fg placeholder:text-fg-subtle focus:border-accent focus:outline-none disabled:opacity-60";

interface FieldProps {
  label: string;
  error?: string;
  hint?: string;
}

export function TextField({
  label,
  error,
  hint,
  className,
  ...props
}: FieldProps & React.InputHTMLAttributes<HTMLInputElement>) {
  const id = useId();
  const describedBy = error ? `${id}-error` : hint ? `${id}-hint` : undefined;
  return (
    <div className={className}>
      <label htmlFor={id} className="mb-1.5 block text-xs font-medium text-fg-muted">
        {label}
      </label>
      <input
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        className={clsx(CONTROL, error ? "border-danger" : "border-border")}
        {...props}
      />
      {error ? (
        <p id={`${id}-error`} className="mt-1 text-xs text-danger">
          {error}
        </p>
      ) : (
        hint && (
          <p id={`${id}-hint`} className="mt-1 text-xs text-fg-subtle">
            {hint}
          </p>
        )
      )}
    </div>
  );
}

export function SelectField({
  label,
  error,
  className,
  children,
  hideLabel,
  ...props
}: FieldProps & { hideLabel?: boolean } & React.SelectHTMLAttributes<HTMLSelectElement>) {
  const id = useId();
  return (
    <div className={className}>
      <label
        htmlFor={id}
        className={clsx("mb-1.5 block text-xs font-medium text-fg-muted", hideLabel && "sr-only")}
      >
        {label}
      </label>
      <select
        id={id}
        aria-invalid={error ? true : undefined}
        className={clsx(CONTROL, "pr-8", error ? "border-danger" : "border-border")}
        {...props}
      >
        {children}
      </select>
      {error && <p className="mt-1 text-xs text-danger">{error}</p>}
    </div>
  );
}
