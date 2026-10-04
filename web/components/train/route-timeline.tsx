import type { RouteStop } from "@/lib/api/types";
import { formatDelayShort } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * Route timeline with a per-stop delay range bar (one series: P50 solid, P90 light, shared scale across stops).
 * Values are always printed as text next to the bar, so nothing relies on colour or hover.
 */
export function DelayRouteTimeline({ route }: { route: RouteStop[] }) {
  const max = Math.max(30, ...route.map((s) => s.delay_p90_min ?? 0));
  return (
    <ol className="relative" aria-label="Route">
      {route.map((s, i) => {
        const terminal = i === 0 || i === route.length - 1;
        const p50 = s.delay_p50_min;
        const p90 = s.delay_p90_min;
        const dayChange = i > 0 && s.day !== route[i - 1]!.day;
        return (
          <li key={s.seq} className="grid grid-cols-[1.25rem_1fr] gap-x-3 sm:grid-cols-[1.25rem_minmax(0,1fr)_minmax(0,14rem)]">
            {/* rail */}
            <div className="relative flex justify-center" aria-hidden>
              <span
                className={cn(
                  "bg-border absolute w-0.5",
                  i === 0 ? "top-3 bottom-0" : i === route.length - 1 ? "top-0 h-3" : "inset-y-0",
                )}
              />
              <span
                className={cn(
                  "relative mt-1.5 rounded-full",
                  terminal ? "bg-primary ring-primary/20 size-3 ring-4" : "bg-card border-primary size-2.5 border-2",
                )}
              />
            </div>
            {/* stop */}
            <div className="min-w-0 pb-4">
              {dayChange && (
                <div className="text-primary -mt-1 mb-1 text-[11px] font-semibold tracking-wide uppercase">Day {s.day}</div>
              )}
              <div className="flex flex-wrap items-baseline gap-x-2">
                <span className="font-mono text-xs font-semibold">{s.code}</span>
                <span className={cn("truncate text-sm", terminal && "font-semibold")}>{s.name}</span>
              </div>
              <div className="text-muted-foreground mt-0.5 flex flex-wrap gap-x-3 text-xs tabular-nums">
                {s.arr && <span>arr {s.arr}</span>}
                {s.dep && <span>dep {s.dep}</span>}
                <span>{s.distance_km} km</span>
                {i === 0 && <span>Day {s.day}</span>}
              </div>
            </div>
            {/* delay bar */}
            <div className="col-start-2 pb-4 sm:col-start-auto sm:pt-1">
              {p50 == null || p90 == null ? (
                <span className="text-muted-foreground text-xs">No delay data</span>
              ) : (
                <div className="flex items-center gap-2">
                  <div
                    className="bg-muted relative h-2 flex-1 overflow-hidden rounded-full"
                    role="img"
                    aria-label={`${s.code}: typical delay ${formatDelayShort(p50)}, late case ${formatDelayShort(p90)}`}
                  >
                    <div className="bg-band absolute inset-y-0 left-0 rounded-full" style={{ width: `${(Math.max(0, p90) / max) * 100}%` }} />
                    <div className="bg-primary absolute inset-y-0 left-0 rounded-full" style={{ width: `${(Math.max(0, p50) / max) * 100}%` }} />
                  </div>
                  <span className="w-24 shrink-0 text-right text-xs tabular-nums">
                    <span className="font-medium">{formatDelayShort(p50)}</span>
                    <span className="text-muted-foreground"> / {formatDelayShort(p90)}</span>
                  </span>
                </div>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
