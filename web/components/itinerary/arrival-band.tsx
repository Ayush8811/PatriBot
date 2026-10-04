import type { Leg } from "@/lib/api/types";
import { formatTime, minutesBetween } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * Visual P50–P90 arrival band against the timetable arrival. A single series: the band is the predicted range,
 * the dot the typical (P50) arrival, the tick the scheduled time. Text alternative in aria-label + legend row.
 */
export function ArrivalBand({ leg, className }: { leg: Pick<Leg, "arr_sched" | "arr_pred_p50" | "arr_pred_p90">; className?: string }) {
  const p50 = minutesBetween(leg.arr_sched, leg.arr_pred_p50);
  const p90 = minutesBetween(leg.arr_sched, leg.arr_pred_p90);
  const lo = Math.min(0, p50) - 15;
  const hi = Math.max(p90, 60) + 15;
  const pos = (m: number) => `${((m - lo) / (hi - lo)) * 100}%`;
  const label = `Timetable arrival ${formatTime(leg.arr_sched)}. Likely arrival ${formatTime(leg.arr_pred_p50)}; late case (P90) ${formatTime(leg.arr_pred_p90)}.`;

  return (
    <div className={cn("space-y-1.5", className)}>
      <div role="img" aria-label={label} className="relative h-5">
        <div className="bg-muted absolute inset-x-0 top-1/2 h-1.5 -translate-y-1/2 rounded-full" />
        <div
          className="bg-band border-primary/40 absolute top-1/2 h-3 -translate-y-1/2 rounded-full border"
          style={{ left: pos(p50), width: `calc(${pos(p90)} - ${pos(p50)})` }}
          title={`Predicted P50–P90: ${formatTime(leg.arr_pred_p50)}–${formatTime(leg.arr_pred_p90)}`}
        />
        <div
          className="bg-foreground absolute top-0 h-5 w-0.5 -translate-x-1/2 rounded-full"
          style={{ left: pos(0) }}
          title={`Timetable ${formatTime(leg.arr_sched)}`}
        />
        <div
          className="bg-primary ring-card absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2"
          style={{ left: pos(p50) }}
          title={`Likely (P50) ${formatTime(leg.arr_pred_p50)}`}
        />
      </div>
      <div className="text-muted-foreground flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] leading-tight" aria-hidden>
        <span className="inline-flex items-center gap-1">
          <span className="bg-foreground inline-block h-2.5 w-0.5 rounded-full" /> Timetable {formatTime(leg.arr_sched)}
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="bg-primary inline-block size-2 rounded-full" /> Likely {formatTime(leg.arr_pred_p50)}
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="bg-band border-primary/40 inline-block h-2 w-3 rounded-full border" /> Late case (P90){" "}
          {formatTime(leg.arr_pred_p90)}
        </span>
      </div>
    </div>
  );
}
