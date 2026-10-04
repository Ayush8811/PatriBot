import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { AdSlot } from "@/components/ad-slot";
import { ItineraryCard } from "@/components/itinerary/itinerary-card";
import { ReliabilityBadge } from "@/components/itinerary/reliability-badge";
import type { Itinerary, Leg } from "@/lib/api/types";

const leg12301: Leg = {
  train_no: "12301",
  train_name: "Howrah Rajdhani",
  train_type: "Rajdhani",
  run_date: "2026-11-21",
  from_code: "HWH",
  from_name: "Howrah Jn",
  to_code: "NDLS",
  to_name: "New Delhi",
  dep_sched: "2026-11-21T16:50:00+05:30",
  arr_sched: "2026-11-22T10:05:00+05:30",
  arr_pred_p50: "2026-11-22T10:38:00+05:30",
  arr_pred_p90: "2026-11-22T11:20:00+05:30",
  journey_min_sched: 1035,
  journey_min_pred_p50: 1068,
  reliability: 0.74,
  history_runs: 41,
  overnight: true,
  classes: ["1A", "2A", "3A"],
};

const direct: Itinerary = {
  id: "d-12301-2026-11-21",
  kind: "direct",
  score: 0.82,
  score_breakdown: { journey_time: 0.9, reliability: 0.8, preference: 1.0, transfer: 1.0 },
  why: ["Fastest predicted journey in the window", "Overnight: departs 16:50, arrives ~10:40"],
  legs: [leg12301],
  layover_min_sched: null,
  layover_min_p90: null,
  split_kind: null,
  warnings: [],
  irctc_url: "https://www.irctc.co.in/nget/train-search",
};

const split: Itinerary = {
  ...direct,
  id: "s-22347-12309-2026-11-21",
  kind: "split",
  score: 0.6,
  legs: [
    {
      ...leg12301,
      train_no: "22347",
      train_name: "Howrah Patna Vande Bharat",
      train_type: "Vande Bharat",
      to_code: "PNBE",
      to_name: "Patna Jn",
      dep_sched: "2026-11-21T05:55:00+05:30",
      arr_sched: "2026-11-21T13:35:00+05:30",
      arr_pred_p50: "2026-11-21T13:47:00+05:30",
      arr_pred_p90: "2026-11-21T14:15:00+05:30",
      overnight: false,
      reliability: 0.95,
      history_runs: 0,
    },
    {
      ...leg12301,
      train_no: "12309",
      train_name: "Patna Rajdhani",
      from_code: "PNBE",
      from_name: "Patna Jn",
      dep_sched: "2026-11-21T19:25:00+05:30",
      arr_sched: "2026-11-22T07:40:00+05:30",
      arr_pred_p50: "2026-11-22T08:02:00+05:30",
      arr_pred_p90: "2026-11-22T08:35:00+05:30",
      reliability: 0.45,
    },
  ],
  layover_min_sched: 350,
  layover_min_p90: 310,
  split_kind: "split_itinerary",
  warnings: ["Separate tickets: a missed connection is not refundable"],
};

describe("ItineraryCard (direct)", () => {
  it("shows train, date, departure, scheduled vs predicted arrival with day offset", () => {
    render(<ItineraryCard itinerary={direct} />);
    const card = screen.getByTestId("itinerary-card");
    expect(within(card).getByText("12301")).toBeInTheDocument();
    expect(within(card).getByText("Howrah Rajdhani")).toBeInTheDocument();
    expect(within(card).getByText("Sat, 21 Nov")).toBeInTheDocument();
    expect(within(card).getByText("16:50")).toBeInTheDocument();
    expect(screen.getByTestId("arr-pred")).toHaveTextContent("10:38+1");
    expect(within(card).getByText("10:05")).toBeInTheDocument();
    expect(within(card).getByText("33 min late")).toBeInTheDocument();
    expect(within(card).getByRole("img", { name: /Likely arrival 10:38; late case \(P90\) 11:20/ })).toBeInTheDocument();
    expect(within(card).getByText("Overnight")).toBeInTheDocument();
    expect(within(card).getByText("based on 41 runs")).toBeInTheDocument();
    expect(within(card).getByText(/Often late · 74% within 30 min/)).toBeInTheDocument();
  });

  it("links to IRCTC in a new tab and to the train page", () => {
    render(<ItineraryCard itinerary={direct} />);
    const irctc = screen.getByRole("link", { name: /check on irctc/i });
    expect(irctc).toHaveAttribute("href", "https://www.irctc.co.in/nget/train-search");
    expect(irctc).toHaveAttribute("target", "_blank");
    expect(irctc).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(screen.getByRole("link", { name: /12301 Howrah Rajdhani/ })).toHaveAttribute("href", "/trains/12301");
  });

  it("expands 'Why this?' to show the score breakdown and reasons", async () => {
    render(<ItineraryCard itinerary={direct} />);
    expect(screen.queryByTestId("why-this")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /why this/i }));
    const why = screen.getByTestId("why-this");
    expect(within(why).getByText("Journey time")).toBeInTheDocument();
    expect(within(why).getByText("90")).toBeInTheDocument();
    expect(within(why).getByText("Fastest predicted journey in the window")).toBeInTheDocument();
  });

  it("marks dates outside the booking window as plan only", () => {
    const { rerender } = render(
      <ItineraryCard itinerary={direct} bookable={{ bookable_from: "2026-10-05", bookable_to: "2026-12-03" }} />,
    );
    expect(screen.queryByText(/plan only/i)).not.toBeInTheDocument();
    rerender(<ItineraryCard itinerary={direct} bookable={{ bookable_from: "2026-10-05", bookable_to: "2026-11-20" }} />);
    expect(screen.getByText(/plan only · not yet bookable/i)).toBeInTheDocument();
  });
});

describe("ItineraryCard (split)", () => {
  it("shows both legs, the layover with P90 risk, warnings and the ticket label", () => {
    render(<ItineraryCard itinerary={split} />);
    expect(screen.getByText("Split · separate tickets")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: /Train 22347/ })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: /Train 12309/ })).toBeInTheDocument();
    const layover = screen.getByTestId("layover");
    expect(layover).toHaveAttribute("data-risk", "safe");
    expect(layover).toHaveTextContent("5h 50m layover");
    expect(layover).toHaveTextContent("5h 10m if leg 1 runs late (P90)");
    expect(screen.getByText("Separate tickets: a missed connection is not refundable")).toBeInTheDocument();
    expect(screen.getByText("Estimate: no history yet")).toBeInTheDocument();
  });

  it("flags a connection that is missed at P90", () => {
    render(<ItineraryCard itinerary={{ ...split, layover_min_p90: -50 }} />);
    expect(screen.getByTestId("layover")).toHaveAttribute("data-risk", "missed");
    expect(screen.getByText("Likely missed if leg 1 is late")).toBeInTheDocument();
  });

  it("labels an official break journey differently", () => {
    render(<ItineraryCard itinerary={{ ...split, split_kind: "break_journey" }} />);
    expect(screen.getByText("Break journey · one ticket")).toBeInTheDocument();
  });
});

describe("ReliabilityBadge", () => {
  it.each([
    [0.8, 41, "high"],
    [0.65, 41, "medium"],
    [0.3, 41, "low"],
    [0.9, 0, "estimate"],
  ] as const)("reliability %s with %s runs → %s", (r, runs, level) => {
    const { container } = render(<ReliabilityBadge reliability={r} historyRuns={runs} />);
    expect(container.querySelector("[data-level]")).toHaveAttribute("data-level", level);
  });
});

describe("AdSlot", () => {
  it("renders nothing when ads are disabled", () => {
    const { container } = render(<AdSlot slot="x" enabled={false} />);
    expect(container).toBeEmptyDOMElement();
  });
  it("renders a labelled slot when enabled", () => {
    render(<AdSlot slot="x" enabled />);
    expect(screen.getByRole("complementary", { name: "Advertisement" })).toBeInTheDocument();
  });
});
