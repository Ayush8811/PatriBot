"use client";

import Link from "next/link";
import {
  ArrowRight,
  CalendarClock,
  ChevronDown,
  ExternalLink,
  Moon,
  Repeat,
  ShieldAlert,
  ShieldCheck,
  ShieldX,
  TriangleAlert,
} from "lucide-react";

import { ArrivalBand } from "@/components/itinerary/arrival-band";
import { ReliabilityBadge } from "@/components/itinerary/reliability-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/misc";
import type { Itinerary, Leg, PlanMeta } from "@/lib/api/types";
import {
  dayOffset,
  delayLabel,
  describeDayOffset,
  formatDate,
  formatDayOffset,
  formatDuration,
  formatTime,
  isBookable,
  istDate,
  itineraryReliability,
  lastLeg,
  layoverRisk,
  minutesBetween,
  totalPredMinutes,
  type LayoverRisk,
} from "@/lib/format";
import { cn } from "@/lib/utils";

type BookableWindow = Pick<PlanMeta, "bookable_from" | "bookable_to">;

export function ItineraryCard({
  itinerary,
  bookable,
  rank,
  className,
}: {
  itinerary: Itinerary;
  bookable?: BookableWindow;
  rank?: number;
  className?: string;
}) {
  const it = itinerary;
  const first = it.legs[0]!;
  const last = lastLeg(it);
  const isSplit = it.kind === "split";
  const planOnly = bookable ? it.legs.some((l) => !isBookable(l.run_date, bookable)) : false;
  const travelDate = istDate(first.dep_sched);
  const titleId = `it-${it.id}-title`;

  return (
    <Card
      data-testid="itinerary-card"
      data-kind={it.kind}
      aria-labelledby={titleId}
      role="article"
      className={cn("gap-0 overflow-hidden py-0", className)}
    >
      {/* Header strip: date, kind, score */}
      <div className="bg-muted/50 flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b px-4 py-2.5 sm:px-5">
        <span id={titleId} className="flex items-center gap-1.5 text-sm font-semibold">
          <CalendarClock className="text-muted-foreground size-4" aria-hidden />
          {formatDate(travelDate)}
          <span className="sr-only">
            {isSplit
              ? `: split journey, ${it.legs.map((l) => l.train_no).join(" then ")}`
              : `: ${first.train_name} ${first.train_no}`}
          </span>
        </span>
        {isSplit ? (
          <Badge variant="secondary">
            <Repeat aria-hidden /> {it.split_kind === "break_journey" ? "Break journey · one ticket" : "Split · separate tickets"}
          </Badge>
        ) : (
          <Badge variant="outline">Direct</Badge>
        )}
        {last.overnight && (
          <Badge variant="secondary" className="bg-primary/10 text-primary">
            <Moon aria-hidden /> Overnight
          </Badge>
        )}
        {planOnly && (
          <Badge variant="warn" title="Outside IRCTC's 60-day advance reservation window">
            Plan only · not yet bookable
          </Badge>
        )}
        <span className="text-muted-foreground ml-auto text-xs tabular-nums" title="Match score (0–100)">
          {rank != null && <span className="mr-2">#{rank}</span>}
          Score <span className="text-foreground font-semibold">{Math.round(it.score * 100)}</span>
        </span>
      </div>

      <div className="space-y-4 px-4 py-4 sm:px-5">
        {isSplit && <SplitSummary itinerary={it} />}
        {it.legs.map((leg, i) => (
          <div key={`${leg.train_no}-${leg.run_date}`} className="space-y-4">
            {i > 0 && <Layover itinerary={it} prev={it.legs[i - 1]!} next={leg} />}
            <LegBlock leg={leg} index={isSplit ? i + 1 : undefined} />
          </div>
        ))}

        {it.warnings.length > 0 && (
          <Alert variant="warn">
            <TriangleAlert aria-hidden />
            <AlertTitle>{isSplit ? "Before you book separate tickets" : "Heads up"}</AlertTitle>
            <AlertDescription>
              <ul className="list-disc space-y-0.5 pl-4">
                {it.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </AlertDescription>
          </Alert>
        )}
      </div>

      <WhyThis itinerary={it} />
    </Card>
  );
}

function TrainTitle({ leg, index }: { leg: Leg; index?: number }) {
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
      {index != null && (
        <span className="bg-primary text-primary-foreground grid size-5 place-items-center rounded-full text-[11px] font-semibold">
          {index}
        </span>
      )}
      <Link
        href={`/trains/${leg.train_no}`}
        className="group inline-flex items-baseline gap-2 font-semibold hover:underline underline-offset-4"
      >
        <span className="bg-secondary rounded px-1.5 py-0.5 font-mono text-xs">{leg.train_no}</span>{" "}
        <span>{leg.train_name}</span>
      </Link>
      <Badge variant="outline" className="font-normal">
        {leg.train_type}
      </Badge>
      <span className="text-muted-foreground text-xs">{leg.classes.join(" · ")}</span>
    </div>
  );
}

function TimeWithOffset({ iso, depIso, className }: { iso: string; depIso: string; className?: string }) {
  const off = dayOffset(depIso, iso);
  return (
    <span className={cn("tabular-nums", className)}>
      {formatTime(iso)}
      {off !== 0 && (
        <sup className="text-muted-foreground ml-0.5 text-[0.6em] font-medium" title={describeDayOffset(off)}>
          {formatDayOffset(off)}
          <span className="sr-only"> ({describeDayOffset(off)})</span>
        </sup>
      )}
    </span>
  );
}

export function LegBlock({ leg, index }: { leg: Leg; index?: number }) {
  const delay = minutesBetween(leg.arr_sched, leg.arr_pred_p50);
  return (
    <section className="space-y-3" aria-label={`Train ${leg.train_no} ${leg.train_name}`}>
      <TrainTitle leg={leg} index={index} />
      <div className="grid grid-cols-[1fr_auto_1fr] items-start gap-2 sm:gap-4">
        <div>
          <div className="text-muted-foreground text-[11px] font-medium tracking-wide uppercase">Departs</div>
          <div className="text-2xl font-semibold tabular-nums">{formatTime(leg.dep_sched)}</div>
          <div className="text-sm">
            <span className="font-mono text-xs font-semibold">{leg.from_code}</span>{" "}
            <span className="text-muted-foreground">{leg.from_name}</span>
          </div>
        </div>
        <div className="text-muted-foreground flex flex-col items-center pt-5 text-xs">
          <span className="text-foreground font-medium tabular-nums" title="Predicted journey time (P50)">
            ~{formatDuration(leg.journey_min_pred_p50)}
          </span>
          <span className="flex w-16 items-center sm:w-24" aria-hidden>
            <span className="bg-border h-px flex-1" />
            <ArrowRight className="size-3.5" />
          </span>
          <span className="tabular-nums">sched {formatDuration(leg.journey_min_sched)}</span>
        </div>
        <div className="text-right">
          <div className="text-muted-foreground text-[11px] font-medium tracking-wide uppercase">Arrives (predicted)</div>
          <div className="text-2xl font-semibold" data-testid="arr-pred">
            <TimeWithOffset iso={leg.arr_pred_p50} depIso={leg.dep_sched} />
          </div>
          <div className="text-sm">
            <span className="font-mono text-xs font-semibold">{leg.to_code}</span>{" "}
            <span className="text-muted-foreground">{leg.to_name}</span>
          </div>
          <div className="text-muted-foreground mt-0.5 text-xs">
            Timetable <TimeWithOffset iso={leg.arr_sched} depIso={leg.dep_sched} className="line-through decoration-1" />{" "}
            · <span className={cn(delay > 30 ? "text-warn font-medium" : "")}>{delayLabel(leg.arr_sched, leg.arr_pred_p50)}</span>
          </div>
        </div>
      </div>
      <ArrivalBand leg={leg} />
      <ReliabilityBadge reliability={leg.reliability} historyRuns={leg.history_runs} />
    </section>
  );
}

function SplitSummary({ itinerary }: { itinerary: Itinerary }) {
  const first = itinerary.legs[0]!;
  const last = lastLeg(itinerary);
  return (
    <div className="bg-accent/50 flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg px-3 py-2 text-sm">
      <span>
        <span className="font-mono text-xs font-semibold">{first.from_code}</span> {formatTime(first.dep_sched)}
        <ArrowRight className="mx-1 inline size-3.5" aria-label="to" />
        <span className="font-mono text-xs font-semibold">{last.to_code}</span>{" "}
        <TimeWithOffset iso={last.arr_pred_p50} depIso={first.dep_sched} />
      </span>
      <span className="text-muted-foreground">~{formatDuration(totalPredMinutes(itinerary))} door to door</span>
      <span className="text-muted-foreground">{itinerary.legs.length} trains</span>
    </div>
  );
}

const RISK: Record<LayoverRisk, { label: string; icon: typeof ShieldCheck; variant: "good" | "warn" | "bad" }> = {
  safe: { label: "Comfortable connection", icon: ShieldCheck, variant: "good" },
  tight: { label: "Tight if leg 1 is late", icon: ShieldAlert, variant: "warn" },
  missed: { label: "Likely missed if leg 1 is late", icon: ShieldX, variant: "bad" },
};

function Layover({ itinerary, prev, next }: { itinerary: Itinerary; prev: Leg; next: Leg }) {
  const risk = layoverRisk(itinerary.layover_min_p90);
  const r = risk ? RISK[risk] : null;
  const sched = itinerary.layover_min_sched ?? minutesBetween(prev.arr_sched, next.dep_sched);
  return (
    <div
      className="relative flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-lg border border-dashed px-3 py-2 text-sm"
      data-testid="layover"
      data-risk={risk ?? undefined}
    >
      <span className="font-medium">
        Change at <span className="font-mono text-xs font-semibold">{next.from_code}</span> {next.from_name}
      </span>
      <span className="text-muted-foreground tabular-nums">{formatDuration(sched)} layover</span>
      {itinerary.layover_min_p90 != null && (
        <span className="text-muted-foreground tabular-nums">
          {itinerary.layover_min_p90 >= 0
            ? `${formatDuration(itinerary.layover_min_p90)} if leg 1 runs late (P90)`
            : `leg 1 P90 arrives ${formatDuration(-itinerary.layover_min_p90)} after leg 2 leaves`}
        </span>
      )}
      {r && (
        <Badge variant={r.variant} className="ml-auto">
          <r.icon aria-hidden /> {r.label}
        </Badge>
      )}
    </div>
  );
}

const COMPONENTS: { key: string; label: string; hint: string }[] = [
  { key: "journey_time", label: "Journey time", hint: "Predicted door-to-door time vs. the fastest option" },
  { key: "reliability", label: "Reliability", hint: "Chance of arriving within 30 min of the timetable" },
  { key: "preference", label: "Your preferences", hint: "Overnight, time windows and classes" },
  { key: "transfer", label: "Connections", hint: "Direct = 1. Splits are penalised by connection risk" },
];

function WhyThis({ itinerary }: { itinerary: Itinerary }) {
  const extra = Object.keys(itinerary.score_breakdown).filter((k) => !COMPONENTS.some((c) => c.key === k));
  const rows = [...COMPONENTS, ...extra.map((k) => ({ key: k, label: k.replace(/_/g, " "), hint: "" }))];
  const reliab = itineraryReliability(itinerary);
  return (
    <Collapsible className="border-t">
      <div className="flex flex-wrap items-center gap-2 px-4 py-2.5 sm:px-5">
        <CollapsibleTrigger asChild>
          <Button variant="ghost" size="sm" className="group -ml-2">
            Why this?
            <ChevronDown className="transition-transform group-data-[state=open]:rotate-180" aria-hidden />
          </Button>
        </CollapsibleTrigger>
        <Button asChild size="sm" className="ml-auto">
          <a href={itinerary.irctc_url} target="_blank" rel="noopener noreferrer">
            Check on IRCTC <ExternalLink aria-hidden />
            <span className="sr-only">(opens in a new tab)</span>
          </a>
        </Button>
      </div>
      <CollapsibleContent className="data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down overflow-hidden">
        <div className="grid gap-5 px-4 pb-4 sm:grid-cols-2 sm:px-5" data-testid="why-this">
          <div>
            <h4 className="mb-2 text-sm font-semibold">Score breakdown</h4>
            <dl className="space-y-2">
              {rows.map((c) => {
                const v = itinerary.score_breakdown[c.key] ?? 0;
                return (
                  <div key={c.key} title={c.hint}>
                    <div className="flex justify-between text-xs">
                      <dt className="capitalize">{c.label}</dt>
                      <dd className="tabular-nums">{Math.round(v * 100)}</dd>
                    </div>
                    <div className="bg-muted mt-1 h-1.5 overflow-hidden rounded-full" aria-hidden>
                      <div className="bg-primary h-full rounded-full" style={{ width: `${Math.max(0, Math.min(1, v)) * 100}%` }} />
                    </div>
                  </div>
                );
              })}
            </dl>
            {itinerary.legs.length > 1 && (
              <p className="text-muted-foreground mt-2 text-xs">
                Combined reliability across both trains ≈ {Math.round(reliab * 100)}%.
              </p>
            )}
          </div>
          <div>
            <h4 className="mb-2 text-sm font-semibold">Why we picked it</h4>
            <ul className="space-y-1.5 text-sm">
              {itinerary.why.map((w) => (
                <li key={w} className="flex gap-2">
                  <span className="bg-primary mt-2 size-1.5 shrink-0 rounded-full" aria-hidden />
                  <span>{w}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
