/** Round-trip a PlanRequest through the /plan page URL so results are shareable and back-button friendly. */
import type { HardConstraint, Objective, PlanRequest } from "./types";

const OBJECTIVES: Objective[] = ["fastest", "most_reliable", "balanced"];
const HARD: HardConstraint[] = ["overnight", "arrive_by", "depart_after", "depart_before", "classes"];
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const CLOCK = /^([01]\d|2[0-3]):[0-5]\d$/;

export interface PlanQueryLabels {
  originName?: string;
  destinationName?: string;
}

export function planRequestToSearchParams(req: PlanRequest, labels: PlanQueryLabels = {}): URLSearchParams {
  const sp = new URLSearchParams();
  const p = req.preferences;
  sp.set("from", req.origin);
  sp.set("to", req.destination);
  if (labels.originName) sp.set("from_name", labels.originName);
  if (labels.destinationName) sp.set("to_name", labels.destinationName);
  sp.set("date_from", req.date_from);
  sp.set("date_to", req.date_to);
  if (p.overnight) sp.set("overnight", "1");
  if (p.arrive_by) sp.set("arrive_by", p.arrive_by);
  if (p.depart_after) sp.set("depart_after", p.depart_after);
  if (p.depart_before) sp.set("depart_before", p.depart_before);
  if (p.classes?.length) sp.set("classes", p.classes.join(","));
  if (p.objective) sp.set("objective", p.objective);
  sp.set("split", p.allow_split === false ? "0" : "1");
  if (p.hard?.length) sp.set("hard", p.hard.join(","));
  return sp;
}

export type ParsedPlanQuery =
  | { ok: true; request: PlanRequest; labels: Required<PlanQueryLabels> }
  | { ok: false; error: string };

/** Parse and validate; `max_results` defaults to 20. */
export function planRequestFromSearchParams(sp: URLSearchParams, maxResults = 20): ParsedPlanQuery {
  const origin = sp.get("from")?.trim();
  const destination = sp.get("to")?.trim();
  const dateFrom = sp.get("date_from") ?? "";
  const dateTo = sp.get("date_to") ?? dateFrom;
  if (!origin || !destination) return { ok: false, error: "Choose where you're travelling from and to." };
  if (origin.toUpperCase() === destination.toUpperCase())
    return { ok: false, error: "Origin and destination must be different." };
  if (!DATE.test(dateFrom) || !DATE.test(dateTo)) return { ok: false, error: "Choose valid travel dates." };
  if (dateTo < dateFrom) return { ok: false, error: "The end date must be on or after the start date." };

  const clock = (k: string) => {
    const v = sp.get(k);
    return v && CLOCK.test(v) ? v : null;
  };
  const objective = sp.get("objective") as Objective | null;
  const classes = (sp.get("classes") ?? "").split(",").map((c) => c.trim()).filter(Boolean);
  const hard = (sp.get("hard") ?? "").split(",").filter((h): h is HardConstraint => HARD.includes(h as HardConstraint));

  return {
    ok: true,
    request: {
      origin,
      destination,
      date_from: dateFrom,
      date_to: dateTo,
      preferences: {
        overnight: sp.get("overnight") === "1",
        depart_after: clock("depart_after"),
        depart_before: clock("depart_before"),
        arrive_by: clock("arrive_by"),
        classes,
        objective: objective && OBJECTIVES.includes(objective) ? objective : "balanced",
        allow_split: sp.get("split") !== "0",
        hard,
      },
      max_results: maxResults,
    },
    labels: {
      originName: sp.get("from_name") || origin,
      destinationName: sp.get("to_name") || destination,
    },
  };
}
