import { CircleAlert, CircleCheck, CircleDashed, CircleX } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  formatPercent,
  historyLabel,
  reliabilityLabel,
  reliabilityLevel,
} from "@/lib/format";
import { cn } from "@/lib/utils";

const VARIANT = { high: "good", medium: "warn", low: "bad" } as const;
const ICON = { high: CircleCheck, medium: CircleAlert, low: CircleX } as const;

/**
 * Reliability = P(arrival within 30 min of schedule). ≥ 0.8 green, 0.5–0.8 amber, < 0.5 red.
 * history_runs = 0 means the number is a fallback estimate, shown as such.
 */
export function ReliabilityBadge({
  reliability,
  historyRuns,
  className,
  showRuns = true,
  observed = false,
}: {
  reliability: number;
  historyRuns: number;
  className?: string;
  showRuns?: boolean;
  /** true: an observed share of collected runs (train page); false: the planner's predicted probability (cards). */
  observed?: boolean;
}) {
  const estimate = historyRuns <= 0;
  const level = reliabilityLevel(reliability);
  const Icon = estimate ? CircleDashed : ICON[level];
  return (
    <span
      className={cn(
        "inline-flex flex-wrap items-center gap-x-2 gap-y-1",
        className,
      )}
    >
      <Badge
        variant={estimate ? "muted" : VARIANT[level]}
        data-level={estimate ? "estimate" : level}
        title={
          observed
            ? "Share of collected runs that arrived within 30 minutes of the timetable"
            : "Predicted chance of arriving within 30 minutes of the timetable"
        }
      >
        <Icon aria-hidden />
        {estimate ? "Estimate" : reliabilityLabel(reliability)} ·{" "}
        {observed
          ? `${formatPercent(reliability)} of runs within 30 min`
          : `~${formatPercent(reliability)} chance within 30 min`}
      </Badge>
      {showRuns && (
        <span className="text-muted-foreground text-xs">
          {historyLabel(historyRuns)}
        </span>
      )}
    </span>
  );
}
