/**
 * Date helpers. The API speaks UTC ISO-8601; the UI shows the user's local time.
 * `<input type="datetime-local">` values ("YYYY-MM-DDTHH:mm") are in local time.
 */

const pad = (n: number) => String(n).padStart(2, '0');

/** ISO (any offset) → "YYYY-MM-DDTHH:mm" in local time, for datetime-local inputs. */
export function toLocalInput(iso: string | Date): string {
  const d = typeof iso === 'string' ? new Date(iso) : iso;
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}`
  );
}

/** datetime-local value → UTC ISO string for the API. */
export function fromLocalInput(value: string): string {
  return new Date(value).toISOString();
}

/** Local calendar date "YYYY-MM-DD". */
export function toLocalDate(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function localTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

const dateTimeFmt = new Intl.DateTimeFormat(undefined, {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
});
const dateFmt = new Intl.DateTimeFormat(undefined, {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
});

export function formatDateTime(iso: string): string {
  return dateTimeFmt.format(new Date(iso));
}

/** "YYYY-MM-DD" (a calendar date, no timezone) → "02 Dec 2026". */
export function formatDate(ymd: string): string {
  const [y, m, d] = ymd.split('-').map(Number);
  return dateFmt.format(new Date(y ?? 0, (m ?? 1) - 1, d ?? 1));
}

/** Compact duration: "2d 4h", "3h 05m", "4m 09s", "12s". */
export function formatDuration(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const d = Math.floor(total / 86_400);
  const h = Math.floor((total % 86_400) / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${pad(m)}m`;
  if (m > 0) return `${m}m ${pad(s)}s`;
  return `${s}s`;
}

/** Minutes → "10 min", "1 h 30 min". */
export function formatMinutes(min: number): string {
  if (min < 60) return `${min} min`;
  const h = Math.floor(min / 60);
  const m = min % 60;
  return m ? `${h} h ${m} min` : `${h} h`;
}
