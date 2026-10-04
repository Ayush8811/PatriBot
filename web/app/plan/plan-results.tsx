"use client";

import * as React from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ArrowRight, ChevronDown, CircleAlert, Pencil, RotateCw, SearchX, TrainFront } from "lucide-react";

import { AdSlot } from "@/components/ad-slot";
import { ItineraryCard } from "@/components/itinerary/itinerary-card";
import { SearchForm } from "@/components/search/search-form";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Alert, AlertDescription, AlertTitle, Skeleton } from "@/components/ui/misc";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { ApiError, api } from "@/lib/api";
import { planRequestFromSearchParams } from "@/lib/api/query";
import type { PlanResponse } from "@/lib/api/types";
import { formatDateRange, formatStamp } from "@/lib/format";
import { FILTERS, SORTS, filterItineraries, sortItineraries, type FilterKey, type SortKey } from "@/lib/itineraries";
import { useAsync } from "@/lib/use-async";

export function PlanResults() {
  const sp = useSearchParams();
  const spKey = sp.toString();
  const parsed = React.useMemo(() => planRequestFromSearchParams(new URLSearchParams(spKey)), [spKey]);
  const state = useAsync<PlanResponse>(parsed.ok ? spKey : null, (signal) =>
    parsed.ok ? api.plan(parsed.request, { signal }) : Promise.reject(new Error("invalid")),
  );
  const [sort, setSort] = React.useState<SortKey>("best");
  const [filters, setFilters] = React.useState<FilterKey[]>([]);

  if (!parsed.ok) {
    return (
      <EmptyState
        icon={<CircleAlert className="size-6" aria-hidden />}
        title="Let's set up your search"
        body={parsed.error}
        action={
          <Card className="mt-6 p-4 text-left sm:p-6">
            <SearchForm compact />
          </Card>
        }
      />
    );
  }

  const { request, labels } = parsed;
  const header = (
    <div className="mb-5 space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="flex flex-wrap items-center gap-x-2 text-2xl font-bold tracking-tight sm:text-3xl">
            {labels.originName} <ArrowRight className="text-muted-foreground size-5" aria-label="to" /> {labels.destinationName}
          </h1>
          <p className="text-muted-foreground mt-1 text-sm">
            Departing {formatDateRange(request.date_from, request.date_to)}
            {request.preferences.overnight && " · overnight preferred"}
            {request.preferences.arrive_by && ` · arrive by ${request.preferences.arrive_by} (P90)`}
            {request.preferences.allow_split === false && " · direct only"}
          </p>
        </div>
      </div>
      <Collapsible>
        <CollapsibleTrigger asChild>
          <Button variant="outline" size="sm" className="group">
            <Pencil aria-hidden /> Modify search
            <ChevronDown className="transition-transform group-data-[state=open]:rotate-180" aria-hidden />
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <Card className="mt-3 p-4 sm:p-5">
            <SearchForm
              key={spKey}
              compact
              initial={{
                origin: { id: request.origin, name: labels.originName },
                destination: { id: request.destination, name: labels.destinationName },
                request,
              }}
            />
          </Card>
        </CollapsibleContent>
      </Collapsible>
    </div>
  );

  if (state.status === "loading") {
    return (
      <>
        {header}
        <ResultsSkeleton />
      </>
    );
  }

  if (state.status === "error") {
    const err = state.error;
    const notFound = err instanceof ApiError && err.status === 404;
    return (
      <>
        {header}
        <Alert variant="destructive">
          <CircleAlert aria-hidden />
          <AlertTitle>{notFound ? "We don't know that place" : "Couldn't load train options"}</AlertTitle>
          <AlertDescription>
            <p>{err.message}</p>
            {!notFound && (
              <Button variant="outline" size="sm" className="mt-2" onClick={state.retry}>
                <RotateCw aria-hidden /> Try again
              </Button>
            )}
          </AlertDescription>
        </Alert>
      </>
    );
  }

  const { itineraries, meta } = state.data;
  const shown = sortItineraries(filterItineraries(itineraries, filters, meta), sort);

  return (
    <>
      {header}
      {itineraries.length === 0 ? (
        <EmptyState
          icon={<SearchX className="size-6" aria-hidden />}
          title="No trains match this search"
          body="Try a wider date range, turn on split journeys, or relax the arrive-by time and class filters."
        />
      ) : (
        <>
          <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <ToggleGroup type="single" value={sort} onValueChange={(v) => v && setSort(v as SortKey)} aria-label="Sort by">
              {SORTS.map((s) => (
                <ToggleGroupItem key={s.key} value={s.key}>
                  {s.label}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
            <ToggleGroup
              type="multiple"
              value={filters}
              onValueChange={(v) => setFilters(v as FilterKey[])}
              aria-label="Filter"
            >
              {FILTERS.map((f) => (
                <ToggleGroupItem key={f.key} value={f.key} className="data-[state=on]:bg-secondary data-[state=on]:text-secondary-foreground">
                  {f.label}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </div>
          <p className="text-muted-foreground mb-3 text-xs" aria-live="polite">
            Showing {shown.length} of {itineraries.length} options · {meta.dates_searched} date
            {meta.dates_searched === 1 ? "" : "s"} searched, {meta.candidates_considered} candidates considered
          </p>
          {shown.length === 0 ? (
            <EmptyState
              icon={<SearchX className="size-6" aria-hidden />}
              title="Nothing left after filters"
              body="Clear a filter chip to see more options."
              action={
                <Button variant="outline" className="mt-4" onClick={() => setFilters([])}>
                  Clear filters
                </Button>
              }
            />
          ) : (
            <ol className="space-y-4" aria-label="Itineraries">
              {shown.map((it, i) => (
                <li key={it.id}>
                  <ItineraryCard itinerary={it} bookable={meta} rank={sort === "best" ? i + 1 : undefined} />
                  {i === 2 && <AdSlot slot="results-inline" className="mt-4" />}
                </li>
              ))}
            </ol>
          )}
        </>
      )}
      <p className="text-muted-foreground mt-6 text-xs">
        Predicted times: model <code className="font-mono">{meta.eta_model}</code>, data as of {formatStamp(meta.data_as_of)}.
        Bookable on IRCTC for journeys {formatDateRange(meta.bookable_from, meta.bookable_to)}.
      </p>
    </>
  );
}

function EmptyState({
  icon,
  title,
  body,
  action,
}: {
  icon: React.ReactNode;
  title: string;
  body: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="bg-card rounded-xl border border-dashed px-6 py-12 text-center" role="status">
      <div className="bg-muted text-muted-foreground mx-auto mb-3 grid size-12 place-items-center rounded-full">{icon}</div>
      <h2 className="text-lg font-semibold">{title}</h2>
      <p className="text-muted-foreground mx-auto mt-1 max-w-md text-sm">{body}</p>
      {action}
      {!action && (
        <Button asChild variant="link" className="mt-2">
          <Link href="/">
            <TrainFront aria-hidden /> New search
          </Link>
        </Button>
      )}
    </div>
  );
}

export function ResultsSkeleton() {
  return (
    <div className="space-y-4" aria-busy="true" aria-label="Loading train options">
      {[0, 1, 2].map((i) => (
        <div key={i} className="bg-card space-y-4 rounded-xl border p-5">
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-5 w-64" />
          <div className="flex justify-between">
            <Skeleton className="h-8 w-20" />
            <Skeleton className="h-8 w-24" />
          </div>
          <Skeleton className="h-3 w-full" />
        </div>
      ))}
    </div>
  );
}
