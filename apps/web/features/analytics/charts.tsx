import { formatDate, formatNumber } from "@/lib/format";

export interface DayValue {
  day: string;
  count: number;
}

/** One series over time. Each column is its whole height to hover, and the numbers are also a table. */
export function DailyBars({ label, data }: { label: string; data: DayValue[] }) {
  const max = Math.max(1, ...data.map((d) => d.count));
  const total = data.reduce((sum, d) => sum + d.count, 0);
  return (
    <figure>
      <div className="flex items-baseline justify-between gap-3">
        <figcaption className="text-xs text-fg-muted">{label}</figcaption>
        <span className="text-sm font-medium tabular-nums">{formatNumber(total)}</span>
      </div>
      <div className="mt-3 flex h-28 items-end gap-0.5 border-b border-border" aria-hidden>
        {data.map((d) => (
          <div key={d.day} className="group relative flex h-full min-w-0 flex-1 items-end hover:bg-surface-raised">
            {d.count > 0 && (
              <div className="w-full rounded-t bg-accent" style={{ height: `${(d.count / max) * 100}%` }} />
            )}
            <div className="pointer-events-none absolute bottom-full left-1/2 z-10 mb-1 hidden -translate-x-1/2 whitespace-nowrap rounded border border-border-strong bg-surface-raised px-2 py-1 text-xs group-hover:block">
              {formatDate(d.day)}: <span className="tabular-nums">{formatNumber(d.count)}</span>
            </div>
          </div>
        ))}
      </div>
      <div className="mt-1 flex justify-between text-[11px] text-fg-subtle">
        <span>{formatDate(data[0]?.day ?? "")}</span>
        <span>Busiest day: {formatNumber(Math.max(0, ...data.map((d) => d.count)))}</span>
        <span>{formatDate(data[data.length - 1]?.day ?? "")}</span>
      </div>
      <details className="mt-2 text-xs text-fg-subtle">
        <summary className="cursor-pointer">Show as a table</summary>
        <table className="mt-2 w-full">
          <thead>
            <tr className="text-left">
              <th className="py-0.5 font-medium">Day</th>
              <th className="py-0.5 text-right font-medium">{label}</th>
            </tr>
          </thead>
          <tbody>
            {data
              .filter((d) => d.count > 0)
              .map((d) => (
                <tr key={d.day}>
                  <td className="py-0.5">{formatDate(d.day)}</td>
                  <td className="py-0.5 text-right tabular-nums">{formatNumber(d.count)}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}

/** Amounts by category, each named and numbered, so the bar is never the only way to read one. */
export function BarList({ items }: { items: { key: string; label: string; count: number }[] }) {
  const max = Math.max(1, ...items.map((i) => i.count));
  return (
    <ul className="space-y-3">
      {items.map((item) => (
        <li key={item.key}>
          <div className="flex justify-between gap-3 text-xs">
            <span className="text-fg-muted">{item.label}</span>
            <span className="tabular-nums">{formatNumber(item.count)}</span>
          </div>
          <div className="mt-1 h-1.5 rounded-full bg-surface-raised">
            {item.count > 0 && (
              <div className="h-full rounded-full bg-accent" style={{ width: `${(item.count / max) * 100}%` }} />
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}
