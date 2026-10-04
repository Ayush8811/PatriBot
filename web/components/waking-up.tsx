import { Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";

/** Shown instead of an error while the free API host wakes up from sleep. */
export function WakingUpNotice({ className, compact = false }: { className?: string; compact?: boolean }) {
  if (compact) {
    return (
      <p role="status" className={cn("text-muted-foreground flex items-center gap-2 px-3 py-2 text-sm", className)}>
        <Loader2 className="size-4 shrink-0 animate-spin" aria-hidden />
        Waking up the server…
      </p>
    );
  }
  return (
    <div
      role="status"
      data-testid="waking-up"
      className={cn("bg-card text-card-foreground flex items-start gap-3 rounded-xl border p-4 text-sm shadow-sm", className)}
    >
      <Loader2 className="text-primary mt-0.5 size-5 shrink-0 animate-spin" aria-hidden />
      <div>
        <p className="font-medium">Waking up the server…</p>
        <p className="text-muted-foreground mt-0.5">
          The PatriBot server sleeps when nobody is using it and can take up to a minute to start. Your results will
          appear here automatically.
        </p>
      </div>
    </div>
  );
}
