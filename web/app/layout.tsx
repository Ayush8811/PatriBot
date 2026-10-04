import type { Metadata, Viewport } from "next";
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";

import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";
import { ThemeProvider } from "@/components/theme";
import { getViewer } from "@/lib/auth/viewer";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "PatriBot · Realistic train trip planner", template: "%s · PatriBot" },
  description:
    "Plan Indian Railways trips with realistic arrival times predicted from historical delays, overnight trains and split journeys.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#fbfbfd" },
    { media: "(prefers-color-scheme: dark)", color: "#141824" },
  ],
};

export default async function RootLayout({ children }: LayoutProps<"/">) {
  const viewer = await getViewer();
  return (
    <html lang="en-IN" suppressHydrationWarning className={`${GeistSans.variable} ${GeistMono.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col font-sans">
        <ThemeProvider>
          <a
            href="#main"
            className="focus:bg-primary focus:text-primary-foreground sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:px-3 focus:py-2"
          >
            Skip to content
          </a>
          <SiteHeader
            viewer={{ user: viewer.status === "ok" ? viewer.user : null, authDisabled: viewer.status === "disabled" }}
          />
          <main id="main" className="flex flex-1 flex-col">
            {children}
          </main>
          <SiteFooter />
        </ThemeProvider>
      </body>
    </html>
  );
}
