import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api/http";
import { mockApi, searchPlacesSync } from "@/lib/api/mock";
import { mockPlan } from "@/lib/api/mock/planner";
import { planRequestFromSearchParams, planRequestToSearchParams } from "@/lib/api/query";
import { SseParser, formatSse } from "@/lib/api/sse";
import type { ChatEvent, PlanRequest } from "@/lib/api/types";

const NOW = new Date("2026-10-04T04:30:00Z");
const base: PlanRequest = {
  origin: "KOLKATA",
  destination: "DELHI",
  date_from: "2026-10-10",
  date_to: "2026-10-11",
  preferences: { objective: "balanced", allow_split: true },
};

describe("SSE parser", () => {
  it("parses events split across chunks and CRLF", () => {
    const p = new SseParser();
    const raw =
      formatSse({ event: "token", data: { text: "Hello " } }) +
      ": keep-alive\r\n\r\n" +
      "event: done\r\ndata: {\"usage\":{\"queries_left_today\":2}}\r\n\r\n";
    const out: ChatEvent[] = [];
    for (let i = 0; i < raw.length; i += 7) out.push(...p.push(raw.slice(i, i + 7)));
    out.push(...p.end());
    expect(out).toEqual([
      { event: "token", data: { text: "Hello " } },
      { event: "done", data: { usage: { queries_left_today: 2 } } },
    ]);
  });

  it("joins multi-line data and ignores unknown events and bad JSON", () => {
    const p = new SseParser();
    const out = p.push('event: itineraries\ndata: [\ndata: ]\n\nevent: ping\ndata: {}\n\nevent: token\ndata: {oops\n\n');
    expect(out).toEqual([{ event: "itineraries", data: [] }]);
  });

  it("flushes a trailing event without a blank line", () => {
    const p = new SseParser();
    expect(p.push('event: error\ndata: {"detail":"x"}')).toEqual([]);
    expect(p.end()).toEqual([{ event: "error", data: { detail: "x" } }]);
  });
});

describe("plan query string", () => {
  it("round-trips a request", () => {
    const req: PlanRequest = {
      ...base,
      preferences: {
        overnight: true,
        depart_after: "16:00",
        depart_before: null,
        arrive_by: "09:00",
        classes: ["3A", "2A"],
        objective: "fastest",
        allow_split: false,
        hard: ["arrive_by", "classes"],
      },
    };
    const sp = planRequestToSearchParams(req, { originName: "Kolkata", destinationName: "Delhi" });
    const parsed = planRequestFromSearchParams(sp);
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;
    expect(parsed.request).toEqual({ ...req, max_results: 20 });
    expect(parsed.labels).toEqual({ originName: "Kolkata", destinationName: "Delhi" });
  });

  it("rejects incomplete or inverted queries", () => {
    expect(planRequestFromSearchParams(new URLSearchParams("from=KOLKATA")).ok).toBe(false);
    expect(
      planRequestFromSearchParams(new URLSearchParams("from=A&to=B&date_from=2026-10-11&date_to=2026-10-10")).ok,
    ).toBe(false);
    expect(planRequestFromSearchParams(new URLSearchParams("from=A&to=a&date_from=2026-10-11")).ok).toBe(false);
  });
});

describe("mock API", () => {
  it("resolves places by name, alias and code", () => {
    expect(searchPlacesSync("kolk")[0]).toMatchObject({ kind: "cluster", id: "KOLKATA" });
    expect(searchPlacesSync("bombay")[0]).toMatchObject({ kind: "cluster", id: "MUMBAI" });
    expect(searchPlacesSync("hwh")[0]).toMatchObject({ kind: "station", id: "HWH", cluster: "KOLKATA" });
  });

  it("plans Kolkata → Delhi with direct and split options in contract shape", () => {
    const res = mockPlan(base, NOW);
    expect(res.itineraries.length).toBeGreaterThanOrEqual(3);
    const trains = new Set(res.itineraries.flatMap((i) => i.legs.map((l) => l.train_no)));
    for (const t of ["12301", "12313", "12309"]) expect(trains).toContain(t);
    const split = res.itineraries.find((i) => i.kind === "split")!;
    expect(split.legs).toHaveLength(2);
    expect(split.split_kind).toBe("split_itinerary");
    expect(split.layover_min_sched).toBeGreaterThan(0);
    expect(split.warnings.join(" ")).toMatch(/separate tickets/i);
    const scores = res.itineraries.map((i) => i.score);
    expect(scores).toEqual([...scores].sort((a, b) => b - a));
    expect(res.meta).toMatchObject({ eta_model: "baseline_hist", bookable_from: "2026-10-04", bookable_to: "2026-12-02" });
    for (const it of res.itineraries)
      for (const l of it.legs) {
        expect(l.dep_sched).toMatch(/\+05:30$/);
        expect(Date.parse(l.arr_pred_p90)).toBeGreaterThanOrEqual(Date.parse(l.arr_pred_p50));
      }
  });

  it("uses the train's origin date as run_date for a leg joined mid-route", () => {
    const res = mockPlan(base, NOW);
    const viaDdu = res.itineraries.find((i) => i.legs[1]?.train_no === "12801");
    expect(viaDdu).toBeDefined();
    const leg2 = viaDdu!.legs[1]!;
    expect(leg2.run_date < leg2.dep_sched.slice(0, 10)).toBe(true);
    expect(viaDdu!.layover_min_p90!).toBeLessThan(0);
  });

  it("honours allow_split=false and hard constraints", () => {
    const direct = mockPlan({ ...base, preferences: { allow_split: false } }, NOW);
    expect(direct.itineraries.every((i) => i.kind === "direct")).toBe(true);
    const overnight = mockPlan({ ...base, preferences: { overnight: true, hard: ["overnight"] } }, NOW);
    expect(overnight.itineraries.length).toBeGreaterThan(0);
    expect(overnight.itineraries.every((i) => i.legs.at(-1)!.overnight)).toBe(true);
    const arriveBy = mockPlan({ ...base, preferences: { arrive_by: "09:00", hard: ["arrive_by"] } }, NOW);
    for (const it of arriveBy.itineraries) expect(it.legs.at(-1)!.arr_pred_p90.slice(11, 16) <= "09:00").toBe(true);
  });

  it("returns 404 for unknown places and 422 for bad ranges", () => {
    expect(() => mockPlan({ ...base, origin: "XYZ" })).toThrowError(ApiError);
    try {
      mockPlan({ ...base, origin: "XYZ" });
    } catch (e) {
      expect((e as ApiError).status).toBe(404);
      expect((e as ApiError).message).toBe("unknown place: XYZ");
    }
    try {
      mockPlan({ ...base, date_to: "2026-10-01" });
    } catch (e) {
      expect((e as ApiError).status).toBe(422);
    }
  });

  it("streams chat tokens, itineraries and done", async () => {
    const events: ChatEvent[] = [];
    for await (const ev of mockApi.chat({ session_id: "t", message: "overnight train Kolkata to Delhi" })) events.push(ev);
    const tokens = events.filter((e) => e.event === "token");
    expect(tokens.length).toBeGreaterThan(5);
    expect(events.some((e) => e.event === "itineraries")).toBe(true);
    const done = events.at(-1)!;
    expect(done.event).toBe("done");
    if (done.event === "done") expect(done.data.usage.queries_left_today).toBe(2);
  });

  it("serves train route and performance", async () => {
    const t = await mockApi.train("12301");
    expect(t.route[0]).toMatchObject({ seq: 1, code: "HWH", arr: null, dep: "16:50", day: 1 });
    expect(t.route.at(-1)).toMatchObject({ code: "NDLS", arr: "10:05", day: 2 });
    const p = await mockApi.performance("12301", 3);
    expect(p.by_month).toHaveLength(3);
    await expect(mockApi.train("99999")).rejects.toMatchObject({ status: 404 });
  });
});
