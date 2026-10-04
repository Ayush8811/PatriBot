import type { Itinerary, PlanMeta } from "@/lib/api/types";
import { isBookable, itineraryReliability, lastLeg, totalPredMinutes } from "@/lib/format";

export type SortKey = "best" | "fastest" | "reliable" | "earliest";
export type FilterKey = "overnight" | "direct" | "bookable";

export const SORTS: { key: SortKey; label: string }[] = [
  { key: "best", label: "Best match" },
  { key: "fastest", label: "Fastest" },
  { key: "reliable", label: "Most reliable" },
  { key: "earliest", label: "Earliest" },
];

export const FILTERS: { key: FilterKey; label: string }[] = [
  { key: "overnight", label: "Overnight" },
  { key: "direct", label: "Direct only" },
  { key: "bookable", label: "Bookable now" },
];

export function sortItineraries(its: Itinerary[], key: SortKey): Itinerary[] {
  const out = [...its];
  const dep = (i: Itinerary) => Date.parse(i.legs[0]!.dep_sched);
  switch (key) {
    case "fastest":
      return out.sort((a, b) => totalPredMinutes(a) - totalPredMinutes(b) || b.score - a.score);
    case "reliable":
      return out.sort((a, b) => itineraryReliability(b) - itineraryReliability(a) || b.score - a.score);
    case "earliest":
      return out.sort((a, b) => dep(a) - dep(b));
    default:
      return out.sort((a, b) => b.score - a.score);
  }
}

export function filterItineraries(
  its: Itinerary[],
  filters: Iterable<FilterKey>,
  meta?: Pick<PlanMeta, "bookable_from" | "bookable_to">,
): Itinerary[] {
  const f = new Set(filters);
  return its.filter(
    (i) =>
      (!f.has("overnight") || lastLeg(i).overnight) &&
      (!f.has("direct") || i.kind === "direct") &&
      (!f.has("bookable") || !meta || i.legs.every((l) => isBookable(l.run_date, meta))),
  );
}
