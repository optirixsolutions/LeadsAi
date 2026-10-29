export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-dvh items-center justify-center px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex items-center justify-center gap-2">
          <span
            aria-hidden
            className="grid size-8 place-items-center rounded-md bg-accent font-mono text-xs font-bold text-accent-fg"
          >
            IQ
          </span>
          <span className="text-lg font-semibold tracking-tight">SalesIQ</span>
        </div>
        {children}
      </div>
    </div>
  );
}
