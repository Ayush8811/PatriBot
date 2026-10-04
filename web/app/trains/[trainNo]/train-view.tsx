"use client";

import Link from "next/link";
import { ArrowLeft, ArrowRight, CircleAlert, RotateCw } from "lucide-react";

import { DelayRouteTimeline } from "@/components/train/route-timeline";
import { MonthlyPerformanceChart, RecentRuns } from "@/components/train/performance";
import { ReliabilityBadge } from "@/components/itinerary/reliability-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription, AlertTitle, Skeleton } from "@/components/ui/misc";
import { ApiError, api } from "@/lib/api";
import type { PerformanceResponse, TrainResponse, Weekday } from "@/lib/api/types";
import { formatDelayShort } from "@/lib/format";
import { useAsync } from "@/lib/use-async";
import { cn } from "@/lib/utils";

const DAYS: Weekday[] = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"];

export function TrainView({ trainNo }: { trainNo: string }) {
  const train = useAsync<TrainResponse>(`train:${trainNo}`, (signal) => api.train(trainNo, { signal }));
  const perf = useAsync<PerformanceResponse>(`perf:${trainNo}`, (signal) => api.performance(trainNo, 3, { signal }));

  if (train.status === "loading") {
    return (
      <div className="space-y-4" aria-busy="true" aria-label="Loading train">
        <Skeleton className="h-8 w-72" />
        <Skeleton className="h-4 w-48" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }
  if (train.status === "error") {
    const nf = train.error instanceof ApiError && train.error.status === 404;
    return (
      <Alert variant="destructive">
        <CircleAlert aria-hidden />
        <AlertTitle>{nf ? `We don't have train ${trainNo}` : "Couldn't load this train"}</AlertTitle>
        <AlertDescription>
          <p>{nf ? "It may not run on one of our corridors yet." : train.error.message}</p>
          {!nf && (
            <Button variant="outline" size="sm" className="mt-2" onClick={train.retry}>
              <RotateCw aria-hidden /> Try again
            </Button>
          )}
        </AlertDescription>
      </Alert>
    );
  }

  const t = train.data;
  const p = perf.status === "success" ? perf.data : null;
  const latest = p?.by_month.at(-1);
  const runsBehind = t.route.at(-1)?.history_runs ?? 0;

  return (
    <div className="space-y-6">
      <div>
        <Button asChild variant="ghost" size="sm" className="-ml-2 mb-2">
          <Link href="/" onClick={(e) => {
            if (window.history.length > 1) {
              e.preventDefault();
              window.history.back();
            }
          }}>
            <ArrowLeft aria-hidden /> Back
          </Link>
        </Button>
        <div className="flex flex-wrap items-center gap-2">
          <span className="bg-secondary rounded-md px-2 py-0.5 font-mono text-sm font-semibold">{t.train_no}</span>
          <Badge variant="outline">{t.train_type}</Badge>
          {t.corridors.map((c) => (
            <Badge key={c} variant="muted" className="font-mono">
              {c}
            </Badge>
          ))}
        </div>
        <h1 className="mt-2 text-2xl font-bold tracking-tight sm:text-3xl">{t.train_name}</h1>
        <p className="text-muted-foreground mt-1 flex flex-wrap items-center gap-1.5 text-sm">
          <span className="text-foreground font-mono font-semibold">{t.origin}</span> {t.route[0]?.name}
          <ArrowRight className="size-3.5" aria-label="to" />
          <span className="text-foreground font-mono font-semibold">{t.destination}</span> {t.route.at(-1)?.name}
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
          <ul className="flex gap-1" aria-label="Running days">
            {DAYS.map((d) => {
              const runs = t.running_days.includes(d);
              return (
                <li
                  key={d}
                  className={cn(
                    "grid h-7 w-9 place-items-center rounded text-[11px] font-medium",
                    runs ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground line-through",
                  )}
                  aria-label={`${d}: ${runs ? "runs" : "does not run"}`}
                >
                  {d.slice(0, 2)}
                </li>
              );
            })}
          </ul>
          <span className="text-muted-foreground text-sm">Classes: {t.classes.join(" · ")}</span>
        </div>
      </div>

      <section aria-label="Headline numbers" className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Runs analysed" value={p ? String(p.runs) : "–"} />
        <Stat label="Runs within 30 min" value={p && p.runs > 0 ? `${Math.round(p.on_time_pct)}%` : "–"} />
        <Stat label="Typical final delay" value={latest ? formatDelayShort(latest.final_delay_p50) : "–"} hint="P50, latest month" />
        <Stat label="Late case" value={latest ? formatDelayShort(latest.final_delay_p90) : "–"} hint="P90, latest month" />
      </section>

      {p && p.runs > 0 && (
        <ReliabilityBadge reliability={p.on_time_pct / 100} historyRuns={p.runs} observed />
      )}
      {runsBehind === 0 && (
        <Alert>
          <CircleAlert aria-hidden />
          <AlertTitle>No running history yet</AlertTitle>
          <AlertDescription>Per-stop delays below are corridor-average estimates, not this train&apos;s own record.</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Route and typical delay at each stop</CardTitle>
          <CardDescription>
            Scheduled times (IST) with predicted arrival delay: the solid bar is the typical delay (P50), the light bar the
            late case (P90).
          </CardDescription>
        </CardHeader>
        <CardContent>
          <DelayRouteTimeline route={t.route} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Monthly performance</CardTitle>
          <CardDescription>Share of runs arriving at the destination within 30 minutes of schedule.</CardDescription>
        </CardHeader>
        <CardContent>
          {perf.status === "loading" && <Skeleton className="h-48 w-full" />}
          {perf.status === "error" && <p className="text-muted-foreground text-sm">Performance data is unavailable right now.</p>}
          {p && p.by_month.length === 0 && (
            <p className="text-muted-foreground text-sm">No completed runs recorded for this train yet.</p>
          )}
          {p && p.by_month.length > 0 && (
            <div className="space-y-6">
              <MonthlyPerformanceChart data={p.by_month} />
              {p.recent_runs.length > 0 && <RecentRuns runs={p.recent_runs} />}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="bg-card rounded-xl border p-3">
      <div className="text-muted-foreground text-xs">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
      {hint && <div className="text-muted-foreground text-[11px]">{hint}</div>}
    </div>
  );
}
