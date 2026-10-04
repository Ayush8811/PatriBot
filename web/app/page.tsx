import Link from "next/link";
import { Clock3, Gauge, MessageSquareText, Moon, Repeat } from "lucide-react";

import { AdSlot } from "@/components/ad-slot";
import { SearchForm } from "@/components/search/search-form";
import { Card } from "@/components/ui/card";
import { todayIst } from "@/lib/format";

// Rendered per request so the default "next weekend" dates are computed for today (IST), not at build time.
export const dynamic = "force-dynamic";

const FEATURES = [
  {
    icon: Clock3,
    title: "Realistic arrivals",
    body: "Every train shows the timetable and the likely arrival (P50) with a late-case band (P90), learned from past runs.",
  },
  {
    icon: Gauge,
    title: "Reliability you can see",
    body: "A clear badge for how often a train arrives within 30 minutes of schedule, and how many runs that's based on.",
  },
  {
    icon: Moon,
    title: "Overnight trains first",
    body: "Leave in the evening, wake up at your destination. Toggle it on and we rank sleeper-friendly options higher.",
  },
  {
    icon: Repeat,
    title: "Smart split journeys",
    body: "When direct trains don't fit, we pair two trains via a hub and flag the connection risk if leg 1 runs late.",
  },
];

export default function HomePage() {
  return (
    <div className="relative">
      <div
        aria-hidden
        className="from-primary/10 via-primary/5 pointer-events-none absolute inset-x-0 top-0 -z-10 h-[420px] bg-gradient-to-b to-transparent"
      />
      <div className="mx-auto w-full max-w-6xl px-4 pt-8 pb-12 sm:pt-14">
        <div className="max-w-2xl">
          <p className="text-primary mb-2 text-sm font-semibold">Indian Railways trip planner</p>
          <h1 className="text-3xl font-bold tracking-tight text-balance sm:text-5xl">
            Know when you&apos;ll <span className="text-primary">actually</span> arrive.
          </h1>
          <p className="text-muted-foreground mt-3 text-base text-pretty sm:text-lg">
            Compare trains by predicted arrival, not just the timetable. Find overnight options and split journeys
            across Kolkata, Delhi, Patna, Mumbai, Bengaluru, Hyderabad and Chennai.
          </p>
        </div>

        <Card className="mt-6 p-4 shadow-lg sm:mt-8 sm:p-6">
          <SearchForm today={todayIst()} />
        </Card>

        <p className="text-muted-foreground mt-4 flex items-center gap-2 text-sm">
          <MessageSquareText className="size-4" aria-hidden />
          Prefer to just ask?{" "}
          <Link href="/chat" className="text-primary font-medium underline-offset-4 hover:underline">
            Describe your trip to PatriBot
          </Link>
        </p>

        <AdSlot slot="home-below-search" className="mt-8" />

        <section aria-labelledby="features" className="mt-12">
          <h2 id="features" className="sr-only">
            What PatriBot does
          </h2>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {FEATURES.map(({ icon: Icon, title, body }) => (
              <div key={title} className="bg-card rounded-xl border p-4">
                <span className="bg-primary/10 text-primary mb-3 grid size-9 place-items-center rounded-lg">
                  <Icon className="size-4.5" aria-hidden />
                </span>
                <h3 className="font-semibold">{title}</h3>
                <p className="text-muted-foreground mt-1 text-sm">{body}</p>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
