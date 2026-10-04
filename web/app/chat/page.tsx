import type { Metadata } from "next";
import Link from "next/link";
import { CalendarRange, Clock3, MessageSquareText, Moon, Search, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

export const metadata: Metadata = { title: "Ask AI · coming soon" };

/*
 * Phase 4 (AI chat) is deferred by the owner, so this route is a "Coming soon" page and the UI never calls
 * POST /chat. The finished chat UI (./chat-view.tsx, SSE client in lib/api) stays in the codebase for Phase 4:
 * to switch it back on, render <ChatView /> here again.
 */

const EXAMPLES = [
  "Overnight train Kolkata → Delhi, Nov 20–30",
  "Reach Patna before 9 am next Friday, from Delhi",
  "Most reliable train Bengaluru → Hyderabad this weekend",
];

const WILL_DO = [
  { icon: MessageSquareText, text: "Understand a trip described in plain language, in English or Hinglish." },
  { icon: CalendarRange, text: "Search every date in your window and every station in both cities." },
  { icon: Clock3, text: "Rank trains by realistic arrival times learned from past delays, not just the timetable." },
  { icon: Moon, text: "Explain each pick: overnight comfort, reliability and split-journey connection risk." },
];

export default function ChatComingSoonPage() {
  return (
    <div className="relative">
      <div
        aria-hidden
        className="from-primary/10 via-primary/5 pointer-events-none absolute inset-x-0 top-0 -z-10 h-[360px] bg-gradient-to-b to-transparent"
      />
      <div className="mx-auto w-full max-w-2xl px-4 py-12 sm:py-16">
        <div className="text-center">
          <span className="bg-saffron/20 text-foreground inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold tracking-wide uppercase">
            <Sparkles className="text-saffron size-3.5" aria-hidden /> Coming soon
          </span>
          <h1 className="mt-4 text-3xl font-bold tracking-tight sm:text-4xl">Ask PatriBot in plain language</h1>
          <p className="text-muted-foreground mx-auto mt-3 max-w-lg">
            Soon you&apos;ll be able to describe a trip the way you&apos;d tell a friend, and PatriBot will plan it with
            the same realistic arrival times as the search.
          </p>
        </div>

        <Card className="mt-8 p-5 sm:p-6">
          <h2 className="text-muted-foreground text-xs font-medium tracking-wide uppercase">Things you&apos;ll be able to ask</h2>
          <ul className="mt-3 space-y-2" aria-label="Example questions">
            {EXAMPLES.map((q) => (
              <li key={q} className="bg-muted/60 rounded-lg px-3 py-2 text-sm">
                &ldquo;{q}&rdquo;
              </li>
            ))}
          </ul>
          <h2 className="text-muted-foreground mt-6 text-xs font-medium tracking-wide uppercase">What it will do</h2>
          <ul className="mt-3 space-y-3">
            {WILL_DO.map(({ icon: Icon, text }) => (
              <li key={text} className="flex items-start gap-3 text-sm">
                <span className="bg-primary/10 text-primary grid size-7 shrink-0 place-items-center rounded-md">
                  <Icon className="size-4" aria-hidden />
                </span>
                <span className="pt-1">{text}</span>
              </li>
            ))}
          </ul>
        </Card>

        <div className="mt-8 text-center">
          <p className="text-muted-foreground text-sm">Until then, the search form does the same planning.</p>
          <Button asChild className="mt-3" size="lg">
            <Link href="/">
              <Search aria-hidden /> Search trains
            </Link>
          </Button>
        </div>
      </div>
    </div>
  );
}
