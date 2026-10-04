/**
 * A tiny deterministic planner over the fixtures, shaped like POST /plan. It exists only so the web app is demoable
 * without the backend; it mimics the contract, not the real planner's ranking.
 */
import {
  addDays,
  daysBetween,
  formatDuration,
  formatPercent,
  formatTime,
  istDate,
  layoverRisk,
  minutesBetween,
  todayIst,
} from "@/lib/format";
import { ApiError } from "../http";
import type { Itinerary, Leg, Objective, PlanRequest, PlanResponse, Weekday } from "../types";
import { CLUSTERS, IRCTC_URL, SPLITS, STATIONS, TRAINS, type FixtureStop, type FixtureTrain } from "./fixtures";

const WEEKDAYS: Weekday[] = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];
const MAX_DAYS = 31;

export function resolvePlace(id: string): string[] {
  const key = id.trim().toUpperCase();
  if (CLUSTERS[key]) return CLUSTERS[key].stations;
  if (STATIONS[key]) return [key];
  throw new ApiError(404, `unknown place: ${id}`);
}

/** Deterministic pseudo-random in [0, 1) from a string. */
export function hash01(str: string): number {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return ((h >>> 0) % 10_000) / 10_000;
}

function weekday(date: string): Weekday {
  return WEEKDAYS[new Date(`${date}T00:00:00Z`).getUTCDay()]!;
}

function at(date: string, hhmm: string): string {
  return `${date}T${hhmm}:00+05:30`;
}

function shift(iso: string, minutes: number): string {
  const d = new Date(Date.parse(iso) + minutes * 60_000 + 330 * 60_000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())}T${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:00+05:30`;
}

/** Overnight per FR-6: departs 16:00–23:59, arrives 04:00–11:00 after ≥ 1 night. */
function isOvernight(dep: string, arr: string): boolean {
  const dh = Number(formatTime(dep).slice(0, 2));
  const ah = Number(formatTime(arr).slice(0, 2));
  return dh >= 16 && ah >= 4 && ah < 11 && istDate(arr) > istDate(dep);
}

/** Build a leg of `train` from stop `from` to stop `to` that departs `from` on calendar date `depDate`. */
export function buildLeg(train: FixtureTrain, from: FixtureStop, to: FixtureStop, depDate: string): Leg | null {
  const runDate = addDays(depDate, -(from.day - 1));
  if (!train.running_days.includes(weekday(runDate))) return null;
  const depSched = at(addDays(runDate, from.day - 1), from.dep!);
  const arrSched = at(addDays(runDate, to.day - 1), to.arr!);
  const jitter = 0.8 + 0.4 * hash01(`${train.train_no}:${runDate}`);
  const p50 = Math.round(to.p50 * jitter);
  const p90 = Math.max(p50 + 5, Math.round(to.p90 * jitter));
  const arrP50 = shift(arrSched, p50);
  const reliability = Math.min(0.97, Math.max(0.05, train.reliability + (0.5 - hash01(`r${train.train_no}${runDate}`)) * 0.08));
  return {
    train_no: train.train_no,
    train_name: train.train_name,
    train_type: train.train_type,
    run_date: runDate,
    from_code: from.code,
    from_name: STATIONS[from.code] ?? from.code,
    to_code: to.code,
    to_name: STATIONS[to.code] ?? to.code,
    dep_sched: depSched,
    arr_sched: arrSched,
    arr_pred_p50: arrP50,
    arr_pred_p90: shift(arrSched, p90),
    journey_min_sched: minutesBetween(depSched, arrSched),
    journey_min_pred_p50: minutesBetween(depSched, arrP50),
    reliability: Math.round(reliability * 100) / 100,
    history_runs: train.history_runs,
    overnight: isOvernight(depSched, arrSched),
    classes: train.classes,
  };
}

function findLeg(train: FixtureTrain, fromSet: string[], toSet: string[], depDate: string): Leg | null {
  const i = train.stops.findIndex((st) => fromSet.includes(st.code) && st.dep);
  if (i < 0) return null;
  const j = train.stops.findIndex((st, k) => k > i && toSet.includes(st.code) && st.arr);
  if (j < 0) return null;
  return buildLeg(train, train.stops[i]!, train.stops[j]!, depDate);
}

interface Candidate {
  kind: "direct" | "split";
  legs: Leg[];
  hubName?: string;
  layoverSched?: number;
  layoverP90?: number;
}

function candidatesFor(origin: string[], dest: string[], date: string): Candidate[] {
  const out: Candidate[] = [];
  for (const train of Object.values(TRAINS)) {
    const leg = findLeg(train, origin, dest, date);
    if (leg) out.push({ kind: "direct", legs: [leg] });
  }
  for (const sp of SPLITS) {
    const t1 = TRAINS[sp.leg1]!;
    const t2 = TRAINS[sp.leg2]!;
    const leg1 = findLeg(t1, origin, [sp.hub], date);
    if (!leg1) continue;
    const leg2 = findLeg(t2, [sp.hub], dest, istDate(leg1.arr_sched));
    if (!leg2) continue;
    out.push({
      kind: "split",
      legs: [leg1, leg2],
      hubName: STATIONS[sp.hub],
      layoverSched: minutesBetween(leg1.arr_sched, leg2.dep_sched),
      layoverP90: minutesBetween(leg1.arr_pred_p90, leg2.dep_sched),
    });
  }
  return out;
}

const WEIGHTS: Record<Objective, { journey_time: number; reliability: number; preference: number; transfer: number }> = {
  fastest: { journey_time: 0.5, reliability: 0.2, preference: 0.2, transfer: 0.1 },
  most_reliable: { journey_time: 0.2, reliability: 0.5, preference: 0.2, transfer: 0.1 },
  balanced: { journey_time: 0.35, reliability: 0.35, preference: 0.2, transfer: 0.1 },
};

const inWindow = (hhmm: string, after?: string | null, before?: string | null) =>
  (!after || hhmm >= after) && (!before || hhmm <= before);

export function mockPlan(req: PlanRequest, now: Date = new Date()): PlanResponse {
  const origin = resolvePlace(req.origin);
  const dest = resolvePlace(req.destination);
  const nDays = daysBetween(req.date_from, req.date_to) + 1;
  if (!(nDays >= 1)) throw new ApiError(422, [{ loc: ["body", "date_to"], msg: "date_to must be on or after date_from", type: "value_error" }]);
  if (nDays > MAX_DAYS) throw new ApiError(422, [{ loc: ["body", "date_to"], msg: `date range is limited to ${MAX_DAYS} days`, type: "value_error" }]);

  const p = req.preferences ?? {};
  const hard = new Set(p.hard ?? []);
  const objective = p.objective ?? "balanced";
  const w = WEIGHTS[objective];

  let cands: Candidate[] = [];
  for (let i = 0; i < nDays; i++) cands.push(...candidatesFor(origin, dest, addDays(req.date_from, i)));
  const considered = cands.length;

  const overnightOf = (c: Candidate) => c.legs[c.legs.length - 1]!.overnight;
  const depOf = (c: Candidate) => formatTime(c.legs[0]!.dep_sched);
  const arrP90Of = (c: Candidate) => formatTime(c.legs[c.legs.length - 1]!.arr_pred_p90);
  const classOk = (c: Candidate) => !p.classes?.length || c.legs.every((l) => l.classes.some((k) => p.classes!.includes(k)));

  cands = cands.filter((c) => {
    if (c.kind === "split" && p.allow_split === false) return false;
    if (hard.has("overnight") && p.overnight && !overnightOf(c)) return false;
    if (hard.has("arrive_by") && p.arrive_by && arrP90Of(c) > p.arrive_by) return false;
    if (hard.has("depart_after") && p.depart_after && depOf(c) < p.depart_after) return false;
    if (hard.has("depart_before") && p.depart_before && depOf(c) > p.depart_before) return false;
    if (hard.has("classes") && !classOk(c)) return false;
    return true;
  });

  const total = (c: Candidate) => minutesBetween(c.legs[0]!.dep_sched, c.legs[c.legs.length - 1]!.arr_pred_p50);
  const fastest = Math.min(...cands.map(total));
  const relOf = (c: Candidate) => c.legs.reduce((a, l) => a * l.reliability, 1);
  const mostReliable = Math.max(...cands.map(relOf));

  const its: Itinerary[] = cands.map((c) => {
    const first = c.legs[0]!;
    const last = c.legs[c.legs.length - 1]!;
    let pref = 1;
    if (p.overnight && !overnightOf(c)) pref -= 0.5;
    if (p.arrive_by && arrP90Of(c) > p.arrive_by) pref -= 0.3;
    if (!inWindow(depOf(c), p.depart_after, p.depart_before)) pref -= 0.3;
    if (!classOk(c)) pref -= 0.3;
    const risk = layoverRisk(c.layoverP90 ?? null);
    const transfer = c.kind === "direct" ? 1 : 0.7 * (risk === "safe" ? 1 : risk === "tight" ? 0.6 : 0.2);
    const breakdown = {
      journey_time: round2(fastest / total(c)),
      reliability: round2(relOf(c)),
      preference: round2(Math.max(0, pref)),
      transfer: round2(transfer),
    };
    const score = round2(
      breakdown.journey_time * w.journey_time +
        breakdown.reliability * w.reliability +
        breakdown.preference * w.preference +
        breakdown.transfer * w.transfer,
    );

    const why: string[] = [];
    if (total(c) === fastest) why.push("Fastest predicted journey in the window");
    if (relOf(c) === mostReliable) why.push("Most reliable option in the window");
    if (overnightOf(c))
      why.push(`Overnight: departs ${formatTime(first.dep_sched)}, arrives ~${formatTime(last.arr_pred_p50)}`);
    why.push(
      `Predicted door-to-door ${formatDuration(total(c))} (timetable ${formatDuration(minutesBetween(first.dep_sched, last.arr_sched))})`,
    );
    for (const l of c.legs) {
      why.push(
        l.history_runs > 0
          ? `${l.train_no} arrives within 30 min of schedule on ${formatPercent(l.reliability)} of ${l.history_runs} recorded runs`
          : `${l.train_no} has no running history yet: its prediction is a corridor-average estimate`,
      );
    }

    const warnings: string[] = [];
    if (c.kind === "split") {
      warnings.push("Separate tickets: a missed connection is not refundable");
      if (risk === "missed")
        warnings.push(
          `If leg 1 runs late (P90) it reaches ${c.hubName} ${formatDuration(-c.layoverP90!)} after leg 2 departs`,
        );
      else if (risk === "tight") warnings.push("Tight connection if leg 1 runs late (P90)");
      why.push(`Split at ${c.hubName}: ${formatDuration(c.layoverSched!)} scheduled layover`);
    }

    return {
      id: `${c.kind === "direct" ? "d" : "s"}-${c.legs.map((l) => l.train_no).join("-")}-${first.run_date}`,
      kind: c.kind,
      score,
      score_breakdown: breakdown,
      why,
      legs: c.legs,
      layover_min_sched: c.layoverSched ?? null,
      layover_min_p90: c.layoverP90 ?? null,
      split_kind: c.kind === "split" ? "split_itinerary" : null,
      warnings,
      irctc_url: IRCTC_URL,
    };
  });

  its.sort((a, b) => b.score - a.score || a.legs[0]!.dep_sched.localeCompare(b.legs[0]!.dep_sched));
  const today = todayIst(now);
  return {
    query: { ...req, origin_stations: origin, destination_stations: dest },
    itineraries: its.slice(0, req.max_results ?? 10),
    meta: {
      eta_model: "baseline_hist",
      data_as_of: `${today}T06:15:00+05:30`,
      dates_searched: nDays,
      candidates_considered: considered,
      bookable_from: today,
      bookable_to: addDays(today, 59),
    },
  };
}

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}
