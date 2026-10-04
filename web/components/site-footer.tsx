import { Info } from "lucide-react";

export const DISCLAIMER =
  "Predictions are estimates from historical running data; not affiliated with Indian Railways/IRCTC.";

export function SiteFooter() {
  return (
    <footer className="text-muted-foreground mt-auto border-t">
      <div className="mx-auto flex max-w-6xl flex-col gap-2 px-4 py-6 text-xs sm:flex-row sm:items-center sm:justify-between">
        <p className="flex items-start gap-2">
          <Info className="mt-px size-3.5 shrink-0" aria-hidden />
          <span>{DISCLAIMER}</span>
        </p>
        <p>All times IST · Book only on irctc.co.in</p>
      </div>
    </footer>
  );
}
