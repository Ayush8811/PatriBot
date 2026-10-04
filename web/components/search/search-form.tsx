"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { ArrowUpDown, CalendarRange, ChevronDown, Info, Moon, Search, SlidersHorizontal, Split } from "lucide-react";

import { PlaceCombobox, type PlaceValue } from "@/components/search/place-combobox";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { planRequestToSearchParams } from "@/lib/api/query";
import type { HardConstraint, Objective, PlanRequest } from "@/lib/api/types";
import { ARP_DAYS } from "@/lib/config";
import { addDays, daysBetween, formatDate, nextWeekend, todayIst } from "@/lib/format";
import { cn } from "@/lib/utils";

export const CLASS_OPTIONS = ["1A", "2A", "3A", "SL", "CC", "EC"] as const;
const OBJECTIVES: { value: Objective; label: string }[] = [
  { value: "balanced", label: "Balanced" },
  { value: "fastest", label: "Fastest" },
  { value: "most_reliable", label: "Most reliable" },
];
const POPULAR: [PlaceValue, PlaceValue][] = [
  [{ id: "KOLKATA", name: "Kolkata" }, { id: "DELHI", name: "Delhi" }],
  [{ id: "DELHI", name: "Delhi" }, { id: "PATNA", name: "Patna" }],
  [{ id: "MUMBAI", name: "Mumbai" }, { id: "DELHI", name: "Delhi" }],
  [{ id: "BENGALURU", name: "Bengaluru" }, { id: "HYDERABAD", name: "Hyderabad" }],
  [{ id: "KOLKATA", name: "Kolkata" }, { id: "CHENNAI", name: "Chennai" }],
];
const MAX_RANGE_DAYS = 31;

export interface SearchFormInitial {
  origin?: PlaceValue | null;
  destination?: PlaceValue | null;
  request?: PlanRequest;
}

export function SearchForm({
  initial,
  compact = false,
  today: todayProp,
}: {
  initial?: SearchFormInitial;
  compact?: boolean;
  /** IST date from the server render, so SSR and hydration agree on the default dates. */
  today?: string;
}) {
  const router = useRouter();
  const req = initial?.request;
  const pref = req?.preferences;
  const [today] = React.useState(() => todayProp ?? todayIst());
  const [weekend] = React.useState(() => nextWeekend(new Date(`${today}T12:00:00+05:30`)));

  const [origin, setOrigin] = React.useState<PlaceValue | null>(initial?.origin ?? null);
  const [destination, setDestination] = React.useState<PlaceValue | null>(initial?.destination ?? null);
  const [dateFrom, setDateFrom] = React.useState(req?.date_from ?? weekend.from);
  const [dateTo, setDateTo] = React.useState(req?.date_to ?? weekend.to);
  const [overnight, setOvernight] = React.useState(pref?.overnight ?? false);
  const [allowSplit, setAllowSplit] = React.useState(pref?.allow_split ?? true);
  const [objective, setObjective] = React.useState<Objective>(pref?.objective ?? "balanced");
  const [arriveBy, setArriveBy] = React.useState(pref?.arrive_by ?? "");
  const [departAfter, setDepartAfter] = React.useState(pref?.depart_after ?? "");
  const [departBefore, setDepartBefore] = React.useState(pref?.depart_before ?? "");
  const [classes, setClasses] = React.useState<string[]>(pref?.classes ?? []);
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const [submitting, setSubmitting] = React.useState(false);

  const arpEnd = addDays(today, ARP_DAYS - 1);
  const beyondArp = dateTo > arpEnd;
  const advancedCount = [arriveBy, departAfter || departBefore, classes.length].filter(Boolean).length;

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (!origin) errs.origin = "Pick a city or station from the list";
    if (!destination) errs.destination = "Pick a city or station from the list";
    if (origin && destination && origin.id === destination.id) errs.destination = "Destination must differ from origin";
    if (!dateFrom || !dateTo) errs.dates = "Choose your travel dates";
    else if (dateTo < dateFrom) errs.dates = "End date must be on or after the start date";
    else if (daysBetween(dateFrom, dateTo) + 1 > MAX_RANGE_DAYS) errs.dates = `Search up to ${MAX_RANGE_DAYS} days at a time`;
    else if (dateFrom < today) errs.dates = "Dates can't be in the past";
    setErrors(errs);
    if (Object.keys(errs).length) return;

    const hard: HardConstraint[] = [];
    if (arriveBy) hard.push("arrive_by");
    if (classes.length) hard.push("classes");
    const request: PlanRequest = {
      origin: origin!.id,
      destination: destination!.id,
      date_from: dateFrom,
      date_to: dateTo,
      preferences: {
        overnight,
        depart_after: departAfter || null,
        depart_before: departBefore || null,
        arrive_by: arriveBy || null,
        classes,
        objective,
        allow_split: allowSplit,
        hard,
      },
    };
    setSubmitting(true);
    const sp = planRequestToSearchParams(request, { originName: origin!.name, destinationName: destination!.name });
    router.push(`/plan?${sp.toString()}`);
  }

  return (
    <form onSubmit={submit} noValidate aria-label="Plan a train trip" className="space-y-5">
      <div className="grid gap-3 md:grid-cols-[1fr_auto_1fr] md:items-end">
        <div>
          <PlaceCombobox
            id="origin"
            label="From"
            placeholder="City or station, e.g. Kolkata"
            value={origin}
            onChange={setOrigin}
            invalid={!!errors.origin}
          />
          {errors.origin && <p className="text-bad mt-1 text-xs">{errors.origin}</p>}
        </div>
        <Button
          type="button"
          variant="outline"
          size="icon"
          aria-label="Swap origin and destination"
          className="mx-auto -my-1 size-9 rounded-full md:mb-1"
          onClick={() => {
            setOrigin(destination);
            setDestination(origin);
          }}
        >
          <ArrowUpDown className="md:rotate-90" aria-hidden />
        </Button>
        <div>
          <PlaceCombobox
            id="destination"
            label="To"
            placeholder="City or station, e.g. Delhi"
            value={destination}
            onChange={setDestination}
            invalid={!!errors.destination}
          />
          {errors.destination && <p className="text-bad mt-1 text-xs">{errors.destination}</p>}
        </div>
      </div>

      <fieldset>
        <legend className="text-muted-foreground mb-1.5 flex items-center gap-1.5 text-xs font-medium tracking-wide uppercase">
          <CalendarRange className="size-3.5" aria-hidden /> Departure dates
        </legend>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label htmlFor="date_from" className="sr-only">
              Earliest departure date
            </Label>
            <Input
              id="date_from"
              type="date"
              min={today}
              value={dateFrom}
              aria-invalid={!!errors.dates || undefined}
              onChange={(e) => {
                setDateFrom(e.target.value);
                if (e.target.value > dateTo) setDateTo(e.target.value);
              }}
              className="h-11"
            />
          </div>
          <div>
            <Label htmlFor="date_to" className="sr-only">
              Latest departure date
            </Label>
            <Input
              id="date_to"
              type="date"
              min={dateFrom || today}
              value={dateTo}
              aria-invalid={!!errors.dates || undefined}
              onChange={(e) => setDateTo(e.target.value)}
              className="h-11"
            />
          </div>
        </div>
        {errors.dates ? (
          <p className="text-bad mt-1 text-xs">{errors.dates}</p>
        ) : (
          <p className={cn("mt-1.5 flex items-start gap-1.5 text-xs", beyondArp ? "text-warn" : "text-muted-foreground")}>
            <Info className="mt-px size-3.5 shrink-0" aria-hidden />
            {beyondArp
              ? `Dates after ${formatDate(arpEnd)} are beyond IRCTC's ${ARP_DAYS}-day booking window: you can plan, not book yet.`
              : `IRCTC opens bookings ${ARP_DAYS} days ahead (until ${formatDate(arpEnd)}). Search up to ${MAX_RANGE_DAYS} days at once.`}
          </p>
        )}
      </fieldset>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="flex items-center justify-between gap-3 rounded-lg border px-3 py-2.5">
          <Label htmlFor="overnight" className="cursor-pointer font-normal">
            <Moon className="text-primary size-4" aria-hidden />
            <span>
              <span className="block font-medium">Overnight</span>
              <span className="text-muted-foreground text-xs">Leave evening, arrive morning</span>
            </span>
          </Label>
          <Switch id="overnight" checked={overnight} onCheckedChange={setOvernight} />
        </div>
        <div className="flex items-center justify-between gap-3 rounded-lg border px-3 py-2.5">
          <Label htmlFor="allow_split" className="cursor-pointer font-normal">
            <Split className="text-primary size-4" aria-hidden />
            <span>
              <span className="block font-medium">Allow split journeys</span>
              <span className="text-muted-foreground text-xs">Two trains via a hub, separate tickets</span>
            </span>
          </Label>
          <Switch id="allow_split" checked={allowSplit} onCheckedChange={setAllowSplit} />
        </div>
      </div>

      <div>
        <div id="objective-label" className="text-muted-foreground mb-1.5 text-xs font-medium tracking-wide uppercase">
          Prioritise
        </div>
        <ToggleGroup
          type="single"
          aria-labelledby="objective-label"
          value={objective}
          onValueChange={(v) => v && setObjective(v as Objective)}
        >
          {OBJECTIVES.map((o) => (
            <ToggleGroupItem key={o.value} value={o.value}>
              {o.label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </div>

      <Collapsible defaultOpen={!compact && advancedCount > 0}>
        <CollapsibleTrigger asChild>
          <Button type="button" variant="ghost" size="sm" className="group -ml-2">
            <SlidersHorizontal aria-hidden /> More options
            {advancedCount > 0 && (
              <span className="bg-primary text-primary-foreground rounded-full px-1.5 text-[10px]">{advancedCount}</span>
            )}
            <ChevronDown className="transition-transform group-data-[state=open]:rotate-180" aria-hidden />
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent className="data-[state=open]:animate-collapsible-down data-[state=closed]:animate-collapsible-up overflow-hidden">
          <div className="grid gap-4 pt-3 sm:grid-cols-3">
            <div>
              <Label htmlFor="arrive_by" className="mb-1.5">
                Must arrive by
              </Label>
              <Input id="arrive_by" type="time" value={arriveBy} onChange={(e) => setArriveBy(e.target.value)} />
              <p className="text-muted-foreground mt-1 text-xs">Checked against the late case (P90), not the timetable.</p>
            </div>
            <fieldset className="sm:col-span-2">
              <legend className="mb-1.5 text-sm font-medium">Departure window</legend>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label htmlFor="depart_after" className="text-muted-foreground mb-1 text-xs font-normal">
                    After
                  </Label>
                  <Input id="depart_after" type="time" value={departAfter} onChange={(e) => setDepartAfter(e.target.value)} />
                </div>
                <div>
                  <Label htmlFor="depart_before" className="text-muted-foreground mb-1 text-xs font-normal">
                    Before
                  </Label>
                  <Input id="depart_before" type="time" value={departBefore} onChange={(e) => setDepartBefore(e.target.value)} />
                </div>
              </div>
            </fieldset>
            <div className="sm:col-span-3">
              <div id="classes-label" className="mb-1.5 text-sm font-medium">
                Classes <span className="text-muted-foreground font-normal">(any if none selected)</span>
              </div>
              <ToggleGroup type="multiple" aria-labelledby="classes-label" value={classes} onValueChange={setClasses}>
                {CLASS_OPTIONS.map((c) => (
                  <ToggleGroupItem key={c} value={c} className="font-mono text-xs">
                    {c}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            </div>
          </div>
        </CollapsibleContent>
      </Collapsible>

      <Button type="submit" size="lg" className="w-full sm:w-auto" disabled={submitting}>
        <Search aria-hidden /> {submitting ? "Searching…" : "Find trains"}
      </Button>

      {!compact && (
        <div className="flex flex-wrap items-center gap-2 pt-1 text-sm">
          <span className="text-muted-foreground text-xs">Popular:</span>
          {POPULAR.map(([a, b]) => (
            <button
              key={`${a.id}-${b.id}`}
              type="button"
              onClick={() => {
                setOrigin(a);
                setDestination(b);
              }}
              className="hover:bg-accent rounded-full border px-2.5 py-1 text-xs transition-colors"
            >
              {a.name} → {b.name}
            </button>
          ))}
        </div>
      )}
    </form>
  );
}
