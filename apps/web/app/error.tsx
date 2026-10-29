"use client";

import { Card, EmptyState } from "@/components/ui/card";

export default function ErrorBoundary({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <Card className="mx-auto mt-24 max-w-lg">
      <EmptyState
        title="Something went wrong"
        body={error.digest ? `Error reference: ${error.digest}` : "An unexpected error occurred."}
      >
        <button
          type="button"
          onClick={reset}
          className="h-9 rounded-md bg-accent px-4 text-sm font-medium text-accent-fg hover:bg-accent-strong"
        >
          Try again
        </button>
      </EmptyState>
    </Card>
  );
}
