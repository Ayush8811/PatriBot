import Link from "next/link";
import { TrainFront } from "lucide-react";

import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="mx-auto flex max-w-md flex-1 flex-col items-center justify-center px-4 py-16 text-center">
      <div className="bg-muted text-muted-foreground mb-4 grid size-14 place-items-center rounded-full">
        <TrainFront className="size-7" aria-hidden />
      </div>
      <h1 className="text-2xl font-bold">Wrong platform</h1>
      <p className="text-muted-foreground mt-2 text-sm">We couldn&apos;t find that page or train.</p>
      <Button asChild className="mt-6">
        <Link href="/">Back to search</Link>
      </Button>
    </div>
  );
}
