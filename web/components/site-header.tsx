"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LogOut, MessageSquareText, Search, TrainFront, UserRound } from "lucide-react";

import { ThemeToggle } from "@/components/theme";
import { Button } from "@/components/ui/button";
import { logout } from "@/lib/auth/actions";
import { API_MOCK } from "@/lib/config";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Search", icon: Search, match: (p: string) => p === "/" || p.startsWith("/plan") },
  { href: "/chat", label: "Ask AI", icon: MessageSquareText, match: (p: string) => p.startsWith("/chat") },
];

export interface HeaderViewer {
  /** signed-in username; null when signed out (the login page) */
  user: string | null;
  /** PATRIBOT_AUTH_DISABLED=1 in mock/dev mode */
  authDisabled: boolean;
}

export function SiteHeader({ viewer }: { viewer: HeaderViewer }) {
  const pathname = usePathname() ?? "/";
  const showNav = viewer.user != null || viewer.authDisabled;
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
          {showNav && NAV.map(({ href, label, icon: Icon, match }) => {
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
          {viewer.user != null && (
            <form action={logout} className="ml-1 flex items-center gap-1">
              <span
                className="text-muted-foreground hidden items-center gap-1 px-1 text-sm md:inline-flex"
                data-testid="signed-in-user"
              >
                <UserRound className="size-4" aria-hidden />
                {viewer.user}
              </span>
              <Button type="submit" variant="outline" size="sm" title={`Signed in as ${viewer.user}. Log out`}>
                <LogOut aria-hidden />
                <span className="hidden sm:inline">Log out</span>
                <span className="sr-only sm:hidden">Log out</span>
              </Button>
            </form>
          )}
          {viewer.authDisabled && (
            <span className="bg-warn-soft text-warn ml-1 rounded-full px-2 py-0.5 text-[11px] font-medium" title="PATRIBOT_AUTH_DISABLED=1 (local dev only)">
              Auth off
            </span>
          )}
        </nav>
      </div>
    </header>
  );
}
