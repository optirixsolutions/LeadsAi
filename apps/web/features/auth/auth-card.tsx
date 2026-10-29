import { Card } from "@/components/ui/card";

export function AuthCard({
  title,
  description,
  children,
  footer,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
}) {
  return (
    <>
      <Card className="p-6">
        <h1 className="text-base font-semibold">{title}</h1>
        {description && <p className="mt-1 text-sm text-fg-muted">{description}</p>}
        <div className="mt-5">{children}</div>
      </Card>
      {footer && <div className="mt-4 text-center text-sm text-fg-muted">{footer}</div>}
    </>
  );
}
