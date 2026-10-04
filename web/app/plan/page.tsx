import type { Metadata } from "next";
import { Suspense } from "react";

import { PlanResults, ResultsSkeleton } from "./plan-results";

export const metadata: Metadata = { title: "Train options" };

export default function PlanPage() {
  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-6 sm:py-8">
      <Suspense fallback={<ResultsSkeleton />}>
        <PlanResults />
      </Suspense>
    </div>
  );
}
