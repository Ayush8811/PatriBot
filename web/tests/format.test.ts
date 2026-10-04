import { describe, expect, it } from "vitest";

import {
  dayOffset,
  delayLabel,
  describeDayOffset,
  formatDate,
  formatDateRange,
  formatDayOffset,
  formatDelay,
  formatDelayShort,
  formatDuration,
  formatTime,
  historyLabel,
  isBookable,
  istDate,
  layoverRisk,
  minutesBetween,
  nextWeekend,
  reliabilityLabel,
  reliabilityLevel,
} from "@/lib/format";

describe("times in IST", () => {
  it("formats the wall-clock time from an offset timestamp", () => {
    expect(formatTime("2026-11-22T10:38:00+05:30")).toBe("10:38");
    expect(formatTime("2026-11-21T23:59:00+05:30")).toBe("23:59");
  });

  it("converts UTC instants to IST, including across midnight", () => {
    expect(formatTime("2026-11-21T18:30:00Z")).toBe("00:00");
    expect(istDate("2026-11-21T18:30:00Z")).toBe("2026-11-22");
    expect(istDate("2026-11-21T18:29:00Z")).toBe("2026-11-21");
  });

  it("computes day offsets across midnight and multi-day runs", () => {
    expect(dayOffset("2026-11-21T16:50:00+05:30", "2026-11-22T10:05:00+05:30")).toBe(1);
    expect(dayOffset("2026-11-21T23:30:00+05:30", "2026-11-22T00:15:00+05:30")).toBe(1);
    expect(dayOffset("2026-11-21T05:55:00+05:30", "2026-11-21T13:35:00+05:30")).toBe(0);
    expect(dayOffset("2026-11-20T21:45:00+05:30", "2026-11-22T07:25:00+05:30")).toBe(2);
    // 31 Dec → 1 Jan
    expect(dayOffset("2026-12-31T22:00:00+05:30", "2027-01-01T06:00:00+05:30")).toBe(1);
  });

  it("labels day offsets", () => {
    expect(formatDayOffset(0)).toBe("");
    expect(formatDayOffset(1)).toBe("+1");
    expect(formatDayOffset(2)).toBe("+2");
    expect(describeDayOffset(0)).toBe("same day");
    expect(describeDayOffset(1)).toBe("next day");
    expect(describeDayOffset(2)).toBe("+2 days");
  });

  it("measures minutes between timestamps with different offsets", () => {
    expect(minutesBetween("2026-11-21T16:50:00+05:30", "2026-11-22T10:05:00+05:30")).toBe(1035);
    expect(minutesBetween("2026-11-21T18:30:00Z", "2026-11-22T00:30:00+05:30")).toBe(30);
  });
});

describe("durations and delays", () => {
  it("formats durations", () => {
    expect(formatDuration(1035)).toBe("17h 15m");
    expect(formatDuration(45)).toBe("45m");
    expect(formatDuration(120)).toBe("2h");
    expect(formatDuration(0)).toBe("0m");
    expect(formatDuration(-50)).toBe("−50m");
  });

  it("labels delays with an on-time tolerance of 5 min", () => {
    expect(formatDelay(0)).toBe("On time");
    expect(formatDelay(5)).toBe("On time");
    expect(formatDelay(-5)).toBe("On time");
    expect(formatDelay(6)).toBe("6 min late");
    expect(formatDelay(33)).toBe("33 min late");
    expect(formatDelay(75)).toBe("1h 15m late");
    expect(formatDelay(-8)).toBe("8 min early");
    expect(formatDelay(null)).toBe("No data");
  });

  it("derives a delay label from scheduled vs predicted arrival, across midnight", () => {
    expect(delayLabel("2026-11-22T10:05:00+05:30", "2026-11-22T10:38:00+05:30")).toBe("33 min late");
    expect(delayLabel("2026-11-21T23:40:00+05:30", "2026-11-22T00:55:00+05:30")).toBe("1h 15m late");
  });

  it("formats short delays for charts", () => {
    expect(formatDelayShort(0)).toBe("0m");
    expect(formatDelayShort(33)).toBe("+33m");
    expect(formatDelayShort(75)).toBe("+1h 15m");
    expect(formatDelayShort(-8)).toBe("−8m");
  });
});

describe("reliability badge thresholds", () => {
  it.each([
    [1, "high"],
    [0.8, "high"],
    [0.79, "medium"],
    [0.5, "medium"],
    [0.49, "low"],
    [0, "low"],
  ] as const)("%s → %s", (r, level) => {
    expect(reliabilityLevel(r)).toBe(level);
  });

  it("has human labels", () => {
    expect(reliabilityLabel(0.84)).toBe("Reliable");
    expect(reliabilityLabel(0.74)).toBe("Often late");
    expect(reliabilityLabel(0.38)).toBe("Usually late");
  });

  it("states the history behind a prediction", () => {
    expect(historyLabel(41)).toBe("based on 41 runs");
    expect(historyLabel(1)).toBe("based on 1 run");
    expect(historyLabel(0)).toMatch(/estimate/i);
  });
});

describe("dates", () => {
  it("formats dates and ranges", () => {
    expect(formatDate("2026-11-21")).toBe("Sat, 21 Nov");
    expect(formatDate("2026-11-21", { year: true, weekday: false })).toBe("21 Nov 2026");
    expect(formatDateRange("2026-10-10", "2026-10-11")).toBe("10–11 Oct");
    expect(formatDateRange("2026-11-28", "2026-12-02")).toBe("28 Nov – 2 Dec");
    expect(formatDateRange("2026-11-21", "2026-11-21")).toBe("21 Nov");
  });

  it("picks the next weekend in IST", () => {
    // Sunday 4 Oct 2026, 10:00 IST → Sat 10 – Sun 11 Oct
    expect(nextWeekend(new Date("2026-10-04T04:30:00Z"))).toEqual({ from: "2026-10-10", to: "2026-10-11" });
    // Friday 9 Oct → the next day
    expect(nextWeekend(new Date("2026-10-09T06:00:00Z"))).toEqual({ from: "2026-10-10", to: "2026-10-11" });
    // Saturday 10 Oct → the following weekend
    expect(nextWeekend(new Date("2026-10-10T06:00:00Z"))).toEqual({ from: "2026-10-17", to: "2026-10-18" });
    // 23:00 UTC Friday is already Saturday in IST
    expect(nextWeekend(new Date("2026-10-09T20:00:00Z"))).toEqual({ from: "2026-10-17", to: "2026-10-18" });
  });

  it("knows the ARP booking window", () => {
    const meta = { bookable_from: "2026-10-05", bookable_to: "2026-12-03" };
    expect(isBookable("2026-10-05", meta)).toBe(true);
    expect(isBookable("2026-12-03", meta)).toBe(true);
    expect(isBookable("2026-12-04", meta)).toBe(false);
  });
});

describe("split journey connection risk", () => {
  it("rates the P90 layover", () => {
    expect(layoverRisk(null)).toBeNull();
    expect(layoverRisk(-20)).toBe("missed");
    expect(layoverRisk(0)).toBe("tight");
    expect(layoverRisk(44)).toBe("tight");
    expect(layoverRisk(45)).toBe("safe");
  });
});
