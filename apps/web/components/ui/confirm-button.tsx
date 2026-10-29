"use client";

import { useState } from "react";

import { Button } from "./button";

/** Two-step destructive action: the first click arms it, the second confirms. */
export function ConfirmButton({
  label,
  confirmLabel,
  onConfirm,
  ariaLabel,
}: {
  label: string;
  confirmLabel: string;
  onConfirm: () => Promise<void>;
  ariaLabel?: string;
}) {
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);

  if (!armed) {
    return (
      <Button variant="ghost" size="sm" onClick={() => setArmed(true)} aria-label={ariaLabel}>
        {label}
      </Button>
    );
  }
  return (
    <span className="inline-flex gap-1">
      <Button
        variant="danger"
        size="sm"
        loading={busy}
        onClick={async () => {
          setBusy(true);
          try {
            await onConfirm();
          } finally {
            setBusy(false);
            setArmed(false);
          }
        }}
      >
        {confirmLabel}
      </Button>
      <Button variant="ghost" size="sm" onClick={() => setArmed(false)} disabled={busy}>
        Cancel
      </Button>
    </span>
  );
}
