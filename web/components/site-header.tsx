"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LogIn, MessageSquareText, Search, TrainFront } from "lucide-react";

import { ThemeToggle } from "@/components/theme";
import { Button } from "@/components/ui/button";
import { AUTH_ENABLED } from "@/lib/auth";
import { API_MOCK } from "@/lib/config";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Search", icon: Search, match: (p: string) => p === "/" || p.startsWith("/plan") },
  { href: "/chat", label: "Ask AI", icon: MessageSquareText, match: (p: string) => p.startsWith("/chat") },
];

export function SiteHeader() {
  const pathname = usePathname() ?? "/";
  return (
    <header className="bg-background/85 supports-[backdrop-filter]:bg-background/70 sticky top-0 z-40 border-b backdrop-blur">
      <div className="mx-auto flex h-14 max-w-6xl items-center gap-2 px-4 sm:gap-4">
        <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight" aria-label="PatriBot home">
          <span className="bg-primary text-primary-foreground grid size-8 place-items-center rounded-lg shadow-sm">
            <TrainFront className="size-4.5" aria-hidden />
          </span>
          <span className="text-lg">
            Patri<span className="text-saffron">Bot</span>
          </span>
        </Link>
        {API_MOCK && (
          <span className="bg-warn-soft text-warn hidden rounded-full px-2 py-0.5 text-[11px] font-medium sm:inline">
            Demo data
          </span>
        )}
        <nav aria-label="Main" className="ml-auto flex items-center gap-1">
          {NAV.map(({ href, label, icon: Icon, match }) => {
            const active = match(pathname);
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "text-muted-foreground hover:text-foreground hover:bg-accent inline-flex h-9 items-center gap-1.5 rounded-md px-2.5 text-sm font-medium transition-colors",
                  active && "text-foreground bg-accent",
                )}
              >
                <Icon className="size-4" aria-hidden />
                <span>{label}</span>
              </Link>
            );
          })}
          <ThemeToggle />
          {/* TODO(auth): Auth.js Google sign-in (lib/auth). Disabled placeholder until then. */}
          <Button
            variant="outline"
            size="sm"
            disabled={!AUTH_ENABLED}
            title="Sign-in with Google is coming soon"
            className="ml-1"
          >
            <LogIn aria-hidden />
            <span className="hidden sm:inline">Sign in</span>
            <span className="sr-only sm:hidden">Sign in (coming soon)</span>
          </Button>
        </nav>
      </div>
    </header>
  );
}
