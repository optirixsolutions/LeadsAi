/**
 * One locale and time zone for all formatting. Pages render on the server and hydrate in
 * the browser; formatting with each runtime's own locale or zone would produce different
 * text and hydration mismatches. Per-user locale and time zone settings come later.
 */
export const APP_LOCALE = "en-US";
export const APP_TIME_ZONE = "UTC";

export function formatNumber(n: number): string {
  return new Intl.NumberFormat(APP_LOCALE).format(n);
}

export function formatMoney(amount: string | number, currency: string): string {
  const value = typeof amount === "string" ? Number(amount) : amount;
  return new Intl.NumberFormat(APP_LOCALE, {
    style: "currency",
    currency,
    maximumFractionDigits: value >= 1000 ? 0 : 2,
  }).format(value);
}

export function formatDate(iso: string): string {
  // Date-only values ("2026-11-30") are calendar dates; never shift them by time zone.
  return new Date(iso).toLocaleDateString(APP_LOCALE, { dateStyle: "medium", timeZone: APP_TIME_ZONE });
}

export function formatDateTime(iso: string): string {
  return `${new Date(iso).toLocaleString(APP_LOCALE, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: APP_TIME_ZONE,
  })} UTC`;
}
