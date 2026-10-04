/** Fixtures-backed implementation of the API (NEXT_PUBLIC_API_MOCK=1). Simulates latency and SSE streaming. */
import { addDays, formatDateRange, formatDuration, formatTime, nextWeekend, todayIst, totalPredMinutes } from "@/lib/format";
import { ApiError, type PatriBotApi } from "../http";
import type { ChatEvent, Itinerary, Place, RouteStop } from "../types";
import { CLUSTERS, STATIONS, TRAINS, clusterPlace, stationPlace } from "./fixtures";
import { hash01, mockPlan } from "./planner";

const sleep = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(t);
      reject(new DOMException("Aborted", "AbortError"));
    });
  });

/** Per-page-load free-tier allowance (D13: 3/day). The real API meters this server-side. */
let queriesLeft = 3;

export function searchPlacesSync(q: string, limit = 10): Place[] {
  const needle = q.trim().toLowerCase();
  if (!needle) return [];
  const out: Place[] = [];
  for (const [id, c] of Object.entries(CLUSTERS)) {
    if (
      id.toLowerCase().startsWith(needle) ||
      c.name.toLowerCase().startsWith(needle) ||
      c.aliases.some((a) => a.startsWith(needle))
    ) {
      out.push(clusterPlace(id));
      for (const code of c.stations) out.push(stationPlace(code));
    }
  }
  for (const [code, name] of Object.entries(STATIONS)) {
    if (out.some((p) => p.id === code)) continue;
    if (code.toLowerCase() === needle || name.toLowerCase().includes(needle)) out.push(stationPlace(code));
  }
  return out.slice(0, limit);
}

export function mockRoute(trainNo: string): RouteStop[] {
  const t = TRAINS[trainNo];
  if (!t) throw new ApiError(404, `unknown train: ${trainNo}`);
  return t.stops.map((st, i) => ({
    seq: i + 1,
    code: st.code,
    name: STATIONS[st.code] ?? st.code,
    arr: st.arr,
    dep: st.dep,
    day: st.day,
    distance_km: st.km,
    delay_p50_min: st.p50,
    delay_p90_min: st.p90,
    history_runs: t.history_runs,
  }));
}

/** Rule-based reply text built only from the itineraries (the LLM must not invent trains, times or rules). */
export function mockReplyText(its: Itinerary[], from: string, to: string, range: string): string {
  if (its.length === 0) {
    return `I couldn't find trains from ${from} to ${to} for ${range} in the demo data. The demo covers Kolkata → Delhi; try "overnight train Kolkata to Delhi next weekend".`;
  }
  const best = its[0]!;
  const l = best.legs[0]!;
  const last = best.legs[best.legs.length - 1]!;
  const via = best.kind === "split" ? ` with a change at ${l.to_name}` : "";
  const parts = [
    `I found ${its.length} option${its.length === 1 ? "" : "s"} from ${from} to ${to} for ${range}. `,
    `My top pick is ${l.train_name} (${l.train_no})${via}, departing ${l.from_code} at ${formatTime(l.dep_sched)} and `,
    `arriving ${last.to_code} around ${formatTime(last.arr_pred_p50)} (timetable ${formatTime(last.arr_sched)}; late case ${formatTime(last.arr_pred_p90)}). `,
    `That's about ${formatDuration(totalPredMinutes(best))} door to door. `,
    `Predicted times come from historical running data, so treat them as estimates. Cards below have the details.`,
  ];
  return parts.join("");
}

function parseChat(message: string): { origin: string; destination: string; from: string; to: string } | null {
  const m = message.toLowerCase();
  const find = (s: string) =>
    Object.entries(CLUSTERS).find(([id, c]) => s.includes(id.toLowerCase()) || c.aliases.some((a) => s.includes(a)))?.[0];
  const split = m.split(/\bto\b|→|->/);
  const origin = split.length > 1 ? find(split[0]!) : undefined;
  const destination = split.length > 1 ? find(split.slice(1).join(" ")) : undefined;
  if (!origin || !destination) return null;
  const wk = nextWeekend();
  return { origin, destination, from: wk.from, to: wk.to };
}

export const mockApi: PatriBotApi = {
  async health() {
    await sleep(50);
    return { status: "ok", data_as_of: `${todayIst()}T06:15:00+05:30`, eta_model: "baseline_hist" };
  },

  async searchPlaces(q, limit = 10, opts) {
    await sleep(120, opts?.signal);
    return { results: searchPlacesSync(q, limit) };
  },

  async plan(req, opts) {
    await sleep(450, opts?.signal);
    return mockPlan(req);
  },

  async train(trainNo, opts) {
    await sleep(250, opts?.signal);
    const t = TRAINS[trainNo];
    if (!t) throw new ApiError(404, `unknown train: ${trainNo}`);
    return {
      train_no: t.train_no,
      train_name: t.train_name,
      train_type: t.train_type,
      origin: t.stops[0]!.code,
      destination: t.stops[t.stops.length - 1]!.code,
      running_days: t.running_days,
      classes: t.classes,
      corridors: t.corridors,
      route: mockRoute(trainNo),
    };
  },

  async performance(trainNo, months = 3, opts) {
    await sleep(250, opts?.signal);
    const t = TRAINS[trainNo];
    if (!t) throw new ApiError(404, `unknown train: ${trainNo}`);
    const final = t.stops[t.stops.length - 1]!;
    const today = todayIst();
    if (t.history_runs === 0) return { train_no: trainNo, runs: 0, on_time_pct: 0, by_month: [], recent_runs: [] };
    const by_month = Array.from({ length: months }, (_, i) => {
      const d = new Date(`${today.slice(0, 7)}-01T00:00:00Z`);
      d.setUTCMonth(d.getUTCMonth() - (months - 1 - i));
      const month = d.toISOString().slice(0, 7);
      const f = 0.75 + 0.5 * hash01(`${trainNo}${month}`);
      return {
        month,
        runs: Math.max(3, Math.round((t.history_runs / months) * (0.8 + 0.4 * hash01(month)))),
        final_delay_p50: Math.round(final.p50 * f),
        final_delay_p90: Math.round(final.p90 * f),
        pct_within_30min: Math.round(Math.min(98, t.reliability * 100 * (1.15 - 0.3 * (f - 0.75)))),
      };
    });
    const recent_runs = Array.from({ length: 10 }, (_, i) => {
      const run_date = addDays(today, -(i + 1));
      const r = hash01(`${trainNo}-${run_date}`);
      return { run_date, final_delay_min: Math.round(final.p50 * (0.2 + 1.8 * r * r)), run_state: "complete" };
    });
    return {
      train_no: trainNo,
      runs: t.history_runs,
      on_time_pct: Math.round(t.reliability * 1000) / 10,
      by_month,
      recent_runs,
    };
  },

  async *chat(req, opts): AsyncGenerator<ChatEvent> {
    try {
      await sleep(300, opts?.signal);
      if (queriesLeft <= 0) {
        yield {
          event: "error",
          data: { detail: "You've used today's free AI queries. The search form is unlimited and free." },
        };
        return;
      }
      queriesLeft -= 1;
      const parsed = parseChat(req.message);
      let its: Itinerary[] = [];
      let text: string;
      if (!parsed) {
        text =
          "Tell me where you're going and roughly when, for example: \"overnight train Kolkata to Delhi next weekend\". " +
          "The demo data covers Kolkata → Delhi.";
      } else {
        const res = mockPlan({
          origin: parsed.origin,
          destination: parsed.destination,
          date_from: parsed.from,
          date_to: parsed.to,
          preferences: { overnight: /overnight|night/i.test(req.message), objective: "balanced", allow_split: true },
          max_results: 3,
        });
        its = res.itineraries;
        text = mockReplyText(
          its,
          CLUSTERS[parsed.origin]!.name,
          CLUSTERS[parsed.destination]!.name,
          formatDateRange(parsed.from, parsed.to),
        );
      }
      for (const token of text.match(/\S+\s*/g) ?? []) {
        await sleep(22, opts?.signal);
        yield { event: "token", data: { text: token } };
      }
      if (its.length) yield { event: "itineraries", data: its };
      yield { event: "done", data: { usage: { queries_left_today: queriesLeft } } };
    } catch (err) {
      if ((err as Error).name === "AbortError") return;
      throw err;
    }
  },
};
