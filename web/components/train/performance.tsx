"use client";

import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { MonthlyPerformance, RecentRun } from "@/lib/api/types";
import { formatDate, formatDelay, formatDelayShort, formatMonth } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Monthly % of runs within 30 min (single series, one hue) + an always-visible table view. */
export function MonthlyPerformanceChart({ data }: { data: MonthlyPerformance[] }) {
  const rows = data.map((d) => ({ ...d, label: formatMonth(d.month) }));
  return (
    <div className="space-y-4">
      <div className="h-48 w-full" aria-hidden>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: -16 }} barCategoryGap="30%">
            <CartesianGrid vertical={false} stroke="var(--border)" />
            <XAxis dataKey="label" tickLine={false} axisLine={false} fontSize={12} stroke="var(--muted-foreground)" />
            <YAxis
              domain={[0, 100]}
              ticks={[0, 50, 100]}
              tickFormatter={(v: number) => `${v}%`}
              tickLine={false}
              axisLine={false}
              fontSize={12}
              stroke="var(--muted-foreground)"
            />
            <Tooltip
              cursor={{ fill: "var(--muted)" }}
              contentStyle={{
                background: "var(--popover)",
                border: "1px solid var(--border)",
                borderRadius: 8,
                color: "var(--popover-foreground)",
                fontSize: 12,
              }}
              formatter={(v) => [`${v}%`, "Within 30 min"]}
            />
            <Bar dataKey="pct_within_30min" fill="var(--primary)" radius={[4, 4, 0, 0]} maxBarSize={56} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm tabular-nums">
          <caption className="sr-only">Monthly performance at the destination</caption>
          <thead className="text-muted-foreground text-xs">
            <tr className="border-b">
              <th scope="col" className="py-2 text-left font-medium">Month</th>
              <th scope="col" className="py-2 text-right font-medium">Runs</th>
              <th scope="col" className="py-2 text-right font-medium">Within 30 min</th>
              <th scope="col" className="py-2 text-right font-medium">Typical delay</th>
              <th scope="col" className="py-2 text-right font-medium">Late case</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.month} className="border-b last:border-0">
                <th scope="row" className="py-2 text-left font-medium">{r.label}</th>
                <td className="py-2 text-right">{r.runs}</td>
                <td className="py-2 text-right">{Math.round(r.pct_within_30min)}%</td>
                <td className="py-2 text-right">{formatDelayShort(r.final_delay_p50)}</td>
                <td className="py-2 text-right">{formatDelayShort(r.final_delay_p90)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** Last N runs: final delay as small bars, coloured by status with the value in the label/tooltip. */
export function RecentRuns({ runs }: { runs: RecentRun[] }) {
  const ordered = [...runs].sort((a, b) => a.run_date.localeCompare(b.run_date));
  const max = Math.max(60, ...ordered.map((r) => r.final_delay_min ?? 0));
  return (
    <div>
      <h4 className="mb-2 text-sm font-semibold">Recent runs</h4>
      <ul className="flex h-24 items-end gap-1.5" aria-label="Final arrival delay of recent runs">
        {ordered.map((r) => {
          const d = r.final_delay_min;
          const label = `${formatDate(r.run_date)}: ${formatDelay(d)}`;
          return (
            <li key={r.run_date} className="group relative flex h-full flex-1 flex-col justify-end" title={label}>
              <span className="sr-only">{label}</span>
              <span
                aria-hidden
                className={cn(
                  "block min-h-1 rounded-t-[4px]",
                  d == null ? "bg-muted" : d <= 30 ? "bg-good" : d <= 90 ? "bg-warn" : "bg-bad",
                )}
                style={{ height: `${d == null ? 4 : Math.max(4, (d / max) * 100)}%` }}
              />
            </li>
          );
        })}
      </ul>
      <div className="text-muted-foreground mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px]" aria-hidden>
        <span className="inline-flex items-center gap-1"><span className="bg-good size-2 rounded-sm" /> ≤ 30 min late</span>
        <span className="inline-flex items-center gap-1"><span className="bg-warn size-2 rounded-sm" /> 31–90 min</span>
        <span className="inline-flex items-center gap-1"><span className="bg-bad size-2 rounded-sm" /> &gt; 90 min</span>
      </div>
    </div>
  );
}
