import type { Metadata } from "next";
import { Lock, TrainFront } from "lucide-react";

import { Card } from "@/components/ui/card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/misc";
import { readAuthConfig } from "@/lib/auth/config";
import { safeNextPath } from "@/lib/auth/next-param";

import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: "Sign in", robots: { index: false, follow: false } };

export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  const sp = await searchParams;
  const next = safeNextPath(typeof sp.next === "string" ? sp.next : null);
  const mode = readAuthConfig().mode;

  return (
    <div className="relative flex flex-1 items-center justify-center px-4 py-12 sm:py-20">
      <div
        aria-hidden
        className="from-primary/10 via-primary/5 pointer-events-none absolute inset-x-0 top-0 -z-10 h-[360px] bg-gradient-to-b to-transparent"
      />
      <div className="w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center text-center">
          <span className="bg-primary text-primary-foreground mb-4 grid size-12 place-items-center rounded-xl shadow-sm">
            <TrainFront className="size-6" aria-hidden />
          </span>
          <h1 className="text-2xl font-bold tracking-tight">Sign in to PatriBot</h1>
          <p className="text-muted-foreground mt-1 text-sm">This is a private preview. Owner access only.</p>
        </div>
        <Card className="p-5 sm:p-6">
          {mode === "misconfigured" ? (
            <Alert variant="destructive" data-testid="auth-not-configured">
              <Lock aria-hidden />
              <AlertTitle>Sign-in is not configured</AlertTitle>
              <AlertDescription>
                <p>
                  This deployment is locked until the owner sets <code>PATRIBOT_AUTH_USER</code>,{" "}
                  <code>PATRIBOT_AUTH_PASSWORD_HASH</code> and <code>PATRIBOT_SESSION_SECRET</code>. See{" "}
                  <code>docs/deploy/vercel.md</code>.
                </p>
              </AlertDescription>
            </Alert>
          ) : (
            <LoginForm next={next} />
          )}
        </Card>
      </div>
    </div>
  );
}
