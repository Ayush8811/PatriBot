/**
 * Formatting helpers. All clock times are shown in IST (UTC+05:30) regardless of the viewer's time zone,
 * because Indian Railways timetables are IST. Pure functions: unit-tested in tests/format.test.ts.
 */
import type { IsoDate, IsoDateTime, Leg, PlanMeta } from "@/lib/api/types";

const IST_OFFSET_MIN = 330;
const MIN = 60_000;
const DAY = 86_400_000;
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] as const;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"] as const;

/** A Date whose UTC fields read as IST wall-clock fields. */
function istShifted(iso: IsoDateTime | Date): Date {
  const ms = typeof iso === "string" ? Date.parse(iso) : iso.getTime();
  if (Number.isNaN(ms)) throw new RangeError(`Invalid date-time: ${String(iso)}`);
  return new Date(ms + IST_OFFSET_MIN * MIN);
}

const pad = (n: number) => String(n).padStart(2, "0");

/** "2026-11-22T10:38:00+05:30" → "10:38" (IST). */
export function formatTime(iso: IsoDateTime): string {
  const d = istShifted(iso);
  return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
}

/** IST calendar date of an instant, "YYYY-MM-DD". */
export function istDate(iso: IsoDateTime | Date): IsoDate {
  const d = istShifted(iso);
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
}

function dateMs(date: IsoDate): number {
  const ms = Date.parse(`${date}T00:00:00Z`);
  if (Number.isNaN(ms)) throw new RangeError(`Invalid date: ${date}`);
  return ms;
}

/** Whole IST calendar days between two instants (arrival day minus departure day). */
export function dayOffset(fromIso: IsoDateTime, toIso: IsoDateTime): number {
  return Math.round((dateMs(istDate(toIso)) - dateMs(istDate(fromIso))) / DAY);
}

/** 0 → "", 1 → "+1", 2 → "+2" (shown next to a clock time). */
export function formatDayOffset(days: number): string {
  return days > 0 ? `+${days}` : days < 0 ? `${days}` : "";
}

/** Long form for screen readers / tooltips: 1 → "next day", 2 → "+2 days". */
export function describeDayOffset(days: number): string {
  if (days === 0) return "same day";
  if (days === 1) return "next day";
  return days > 0 ? `+${days} days` : `${days} days`;
}

export function minutesBetween(fromIso: IsoDateTime, toIso: IsoDateTime): number {
  return Math.round((Date.parse(toIso) - Date.parse(fromIso)) / MIN);
}

/** 1035 → "17h 15m", 45 → "45m", 120 → "2h". Negative values keep their sign. */
export function formatDuration(min: number): string {
  const sign = min < 0 ? "−" : "";
  const abs = Math.abs(Math.round(min));
  const h = Math.floor(abs / 60);
  const m = abs % 60;
  if (h === 0) return `${sign}${m}m`;
  return m === 0 ? `${sign}${h}h` : `${sign}${h}h ${m}m`;
}

export const ON_TIME_TOLERANCE_MIN = 5;

/** Delay in minutes → "On time" | "33 min late" | "1h 15m late" | "8 min early". */
export function formatDelay(min: number | null | undefined): string {
  if (min == null || Number.isNaN(min)) return "No data";
  const m = Math.round(min);
  if (m < -ON_TIME_TOLERANCE_MIN) return `${formatDelayAmount(-m)} early`;
  if (m <= ON_TIME_TOLERANCE_MIN) return "On time";
  return `${formatDelayAmount(m)} late`;
}

/** Compact delay for charts and chips: "+33m", "+1h 15m", "−8m", "0m". */
export function formatDelayShort(min: number): string {
  const m = Math.round(min);
  if (m === 0) return "0m";
  return `${m > 0 ? "+" : "−"}${formatDuration(Math.abs(m))}`;
}

function formatDelayAmount(m: number): string {
  return m < 60 ? `${m} min` : formatDuration(m);
}

/** Predicted vs scheduled arrival as a delay label. */
export function delayLabel(schedIso: IsoDateTime, predIso: IsoDateTime): string {
  return formatDelay(minutesBetween(schedIso, predIso));
}

/** "2026-11-21" → "Sat, 21 Nov" (or "Sat, 21 Nov 2026" with year). */
export function formatDate(date: IsoDate, opts: { year?: boolean; weekday?: boolean } = {}): string {
  const d = new Date(dateMs(date));
  const base = `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}${opts.year ? ` ${d.getUTCFullYear()}` : ""}`;
  return opts.weekday === false ? base : `${WEEKDAYS[d.getUTCDay()]}, ${base}`;
}

/** "10–11 Oct", "28 Nov – 2 Dec", "21 Nov" */
export function formatDateRange(from: IsoDate, to: IsoDate): string {
  if (from === to) return formatDate(from, { weekday: false });
  const a = new Date(dateMs(from));
  const b = new Date(dateMs(to));
  if (a.getUTCMonth() === b.getUTCMonth() && a.getUTCFullYear() === b.getUTCFullYear()) {
    return `${a.getUTCDate()}–${b.getUTCDate()} ${MONTHS[b.getUTCMonth()]}`;
  }
  return `${formatDate(from, { weekday: false })} – ${formatDate(to, { weekday: false })}`;
}

/** "2026-10" → "Oct 2026" */
export function formatMonth(month: string): string {
  const [y, m] = month.split("-").map(Number);
  return `${MONTHS[(m ?? 1) - 1]} ${y}`;
}

export function addDays(date: IsoDate, days: number): IsoDate {
  return new Date(dateMs(date) + days * DAY).toISOString().slice(0, 10);
}

export function daysBetween(from: IsoDate, to: IsoDate): number {
  return Math.round((dateMs(to) - dateMs(from)) / DAY);
}

/** Today's date in IST. */
export function todayIst(now: Date = new Date()): IsoDate {
  return istDate(now);
}

/** The coming Saturday–Sunday (IST). On a Saturday or Sunday it is the following weekend. */
export function nextWeekend(now: Date = new Date()): { from: IsoDate; to: IsoDate } {
  const today = todayIst(now);
  const dow = new Date(dateMs(today)).getUTCDay(); // 0 = Sun
  const toSat = dow === 6 ? 7 : 6 - dow;
  const from = addDays(today, toSat);
  return { from, to: addDays(from, 1) };
}

/** IST "data as of" stamp: "5 Oct, 06:15 IST". */
export function formatStamp(iso: IsoDateTime): string {
  return `${formatDate(istDate(iso), { weekday: false })}, ${formatTime(iso)} IST`;
}

// ---- Reliability -------------------------------------------------------------------------------------------------

export type ReliabilityLevel = "high" | "medium" | "low";

/** Badge thresholds: ≥ 0.8 high (green), 0.5–0.8 medium (amber), < 0.5 low (red). */
export function reliabilityLevel(r: number): ReliabilityLevel {
  if (r >= 0.8) return "high";
  if (r >= 0.5) return "medium";
  return "low";
}

export function reliabilityLabel(r: number): string {
  return { high: "Reliable", medium: "Often late", low: "Usually late" }[reliabilityLevel(r)];
}

export function formatPercent(r: number): string {
  return `${Math.round(r * 100)}%`;
}

/** "based on 41 runs" | "based on 1 run" | "estimate (no history yet)" */
export function historyLabel(runs: number): string {
  if (runs <= 0) return "Estimate: no history yet";
  return `based on ${runs} run${runs === 1 ? "" : "s"}`;
}

// ---- Split journeys -----------------------------------------------------------------------------------------------

export type LayoverRisk = "safe" | "tight" | "missed";
/** Default min connection buffer (architecture §7.2). */
export const MIN_BUFFER_MIN = 45;

/** Risk from the P90 layover (leg2 departure − leg1 P90 arrival). */
export function layoverRisk(layoverP90: number | null): LayoverRisk | null {
  if (layoverP90 == null) return null;
  if (layoverP90 < 0) return "missed";
  if (layoverP90 < MIN_BUFFER_MIN) return "tight";
  return "safe";
}

// ---- Itinerary helpers --------------------------------------------------------------------------------------------

export function firstLeg<T extends { legs: Leg[] }>(it: T): Leg {
  return it.legs[0]!;
}
export function lastLeg<T extends { legs: Leg[] }>(it: T): Leg {
  return it.legs[it.legs.length - 1]!;
}

/** Door-to-door predicted minutes (first departure → last P50 arrival). */
export function totalPredMinutes(it: { legs: Leg[] }): number {
  return minutesBetween(firstLeg(it).dep_sched, lastLeg(it).arr_pred_p50);
}

/** Itinerary reliability = product of leg reliabilities (independence assumption, display only). */
export function itineraryReliability(it: { legs: Leg[] }): number {
  return it.legs.reduce((acc, l) => acc * l.reliability, 1);
}

/** Dates outside the ARP window are plan-only (not yet bookable on IRCTC). */
export function isBookable(runDate: IsoDate, meta: Pick<PlanMeta, "bookable_from" | "bookable_to">): boolean {
  return runDate >= meta.bookable_from && runDate <= meta.bookable_to;
}
