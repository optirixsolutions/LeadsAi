import Link from "next/link";

import { Card, EmptyState } from "@/components/ui/card";

export default function NotFound() {
  return (
    <Card className="mx-auto max-w-lg">
      <EmptyState title="Page not found" body="This page does not exist or has not been built yet.">
        <Link href="/" className="text-sm text-accent hover:underline">
          Back to overview
        </Link>
      </EmptyState>
    </Card>
  );
}
