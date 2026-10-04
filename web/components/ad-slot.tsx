import { ADS_ENABLED } from "@/lib/config";
import { cn } from "@/lib/utils";

/**
 * FR-26: ad slot (e.g. AdSense) on search and result pages. Off unless NEXT_PUBLIC_ADS_ENABLED=1, in which case it
 * renders a labelled placeholder container. TODO(ads): load the ad network script and unit id here.
 */
export function AdSlot({ slot, className, enabled = ADS_ENABLED }: { slot: string; className?: string; enabled?: boolean }) {
  if (!enabled) return null;
  return (
    <aside
      aria-label="Advertisement"
      data-ad-slot={slot}
      className={cn(
        "text-muted-foreground grid min-h-24 place-items-center rounded-xl border border-dashed text-xs",
        className,
      )}
    >
      Advertisement
    </aside>
  );
}
