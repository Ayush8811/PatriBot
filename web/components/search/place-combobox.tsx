"use client";

import * as React from "react";
import { Building2, Loader2, MapPin, TrainTrack } from "lucide-react";

import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import type { Place } from "@/lib/api/types";
import { cn } from "@/lib/utils";

export interface PlaceValue {
  id: string;
  name: string;
}

export function placeLabel(p: Place): string {
  return p.kind === "cluster" ? p.name.replace(/\s*\(all stations\)\s*$/i, "") : `${p.name} (${p.id})`;
}

/** Accessible autocomplete (WAI-ARIA combobox pattern) backed by GET /places/search. */
export function PlaceCombobox({
  id,
  label,
  value,
  onChange,
  placeholder,
  invalid,
}: {
  id: string;
  label: string;
  value: PlaceValue | null;
  onChange: (v: PlaceValue | null) => void;
  placeholder?: string;
  invalid?: boolean;
}) {
  const [text, setText] = React.useState(value?.name ?? "");
  const [results, setResults] = React.useState<Place[]>([]);
  const [open, setOpen] = React.useState(false);
  const [active, setActive] = React.useState(-1);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const listId = `${id}-listbox`;

  // Keep the text in sync when the value is set from outside (swap, popular routes).
  const [lastValue, setLastValue] = React.useState(value);
  if (value !== lastValue) {
    setLastValue(value);
    setText(value?.name ?? "");
  }

  React.useEffect(() => {
    const q = text.trim();
    if (!open || q.length < 2 || (value && q === value.name)) return;
    const ctrl = new AbortController();
    const t = setTimeout(() => {
      setLoading(true);
      api
        .searchPlaces(q, 10, { signal: ctrl.signal })
        .then((r) => {
          setResults(r.results);
          setActive(r.results.length ? 0 : -1);
          setError(null);
        })
        .catch((e: Error) => {
          if (e.name !== "AbortError") setError("Couldn't load places");
        })
        .finally(() => setLoading(false));
    }, 180);
    return () => {
      clearTimeout(t);
      ctrl.abort();
    };
  }, [text, open, value]);

  const select = (p: Place) => {
    const v = { id: p.id, name: placeLabel(p) };
    onChange(v);
    setText(v.name);
    setOpen(false);
  };

  const showList = open && text.trim().length >= 2 && !(value && text === value.name);

  return (
    <div className="relative">
      <label htmlFor={id} className="text-muted-foreground mb-1.5 block text-xs font-medium tracking-wide uppercase">
        {label}
      </label>
      <div className="relative">
        <MapPin className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2" aria-hidden />
        <Input
          id={id}
          role="combobox"
          aria-expanded={showList}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={showList && active >= 0 ? `${id}-opt-${active}` : undefined}
          aria-invalid={invalid || undefined}
          autoComplete="off"
          placeholder={placeholder}
          className="h-11 pl-9 text-base"
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setOpen(true);
            if (value) onChange(null);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 120)}
          onKeyDown={(e) => {
            if (!showList) return;
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setActive((a) => Math.min(results.length - 1, a + 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setActive((a) => Math.max(0, a - 1));
            } else if (e.key === "Enter" && active >= 0 && results[active]) {
              e.preventDefault();
              select(results[active]!);
            } else if (e.key === "Escape") {
              setOpen(false);
            }
          }}
        />
        {loading && (
          <Loader2 className="text-muted-foreground absolute top-1/2 right-3 size-4 -translate-y-1/2 animate-spin" aria-hidden />
        )}
      </div>
      {showList && (
        <ul
          id={listId}
          role="listbox"
          aria-label={`${label} suggestions`}
          className="bg-popover text-popover-foreground absolute z-30 mt-1 max-h-72 w-full overflow-auto rounded-lg border p-1 shadow-lg"
        >
          {error && <li className="text-bad px-3 py-2 text-sm">{error}</li>}
          {!error && !loading && results.length === 0 && (
            <li className="text-muted-foreground px-3 py-2 text-sm">No matching city or station</li>
          )}
          {results.map((p, i) => (
            <li
              key={`${p.kind}-${p.id}`}
              id={`${id}-opt-${i}`}
              role="option"
              aria-selected={i === active}
              onMouseDown={(e) => {
                e.preventDefault();
                select(p);
              }}
              onMouseEnter={() => setActive(i)}
              className={cn(
                "flex cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-2 text-sm",
                i === active && "bg-accent text-accent-foreground",
                p.kind === "station" && "pl-7",
              )}
            >
              {p.kind === "cluster" ? (
                <Building2 className="text-primary size-4 shrink-0" aria-hidden />
              ) : (
                <TrainTrack className="text-muted-foreground size-3.5 shrink-0" aria-hidden />
              )}
              <span className="flex-1 truncate">
                {p.kind === "cluster" ? <span className="font-medium">{p.name}</span> : p.name}
              </span>
              <span className="text-muted-foreground font-mono text-xs">
                {p.kind === "cluster" ? p.stations.slice(0, 4).join(" ") : p.id}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
