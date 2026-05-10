"use client";

import Image from "next/image";
import { useTheme } from "next-themes";
import {
  Activity,
  ArrowRight,
  Brain,
  FileText,
  Loader2,
  LockKeyhole,
  Moon,
  ShieldCheck,
  Sun,
} from "lucide-react";
import { useAuth } from "./providers/auth-provider";

/**
 * Renders nothing until Keycloak is ready; gates children behind authentication.
 * Used at the app root — every page below the layout assumes authenticated state.
 */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const { ready, authenticated, login } = useAuth();
  const { resolvedTheme, setTheme } = useTheme();
  const dark = resolvedTheme === "dark";

  if (!ready) {
    return (
      <div className="grid min-h-screen place-items-center bg-grad-cosmic">
        <div className="flex items-center gap-3 text-ink-1">
          <Loader2 className="h-5 w-5 animate-spin text-cy" />
          <span>Connecting to Keycloak…</span>
        </div>
      </div>
    );
  }

  if (!authenticated) {
    return (
      <LoginScreen login={login} dark={dark} setTheme={setTheme} />
    );
  }

  return <>{children}</>;
}

function LoginScreen({
  login,
  dark,
  setTheme,
}: {
  login: () => void;
  dark: boolean;
  setTheme: (theme: string) => void;
}) {
  return (
    <div className="relative min-h-screen overflow-hidden bg-grad-cosmic text-ink-0">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_20%_15%,hsl(var(--cy)/0.20),transparent_32%),radial-gradient(circle_at_82%_20%,hsl(var(--vio)/0.18),transparent_34%),linear-gradient(135deg,hsl(var(--bg-0)),hsl(var(--bg-1)))]" />
      <div className="absolute inset-x-0 bottom-0 h-48 bg-gradient-to-t from-bg-0 to-transparent" />

      <button
        type="button"
        onClick={() => setTheme(dark ? "light" : "dark")}
        className="absolute right-5 top-5 z-10 grid h-10 w-10 place-items-center rounded-lg border border-line-subtle bg-bg-1/80 text-ink-1 shadow-sm backdrop-blur transition hover:bg-bg-2 hover:text-ink-0"
        aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
        title={dark ? "Switch to light mode" : "Switch to dark mode"}
      >
        {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
      </button>

      <main className="relative z-10 mx-auto grid min-h-screen w-full max-w-6xl grid-cols-1 items-center gap-10 px-6 py-12 lg:grid-cols-[1.05fr_0.95fr]">
        <section className="space-y-8">
          <div className="flex items-center gap-4">
            <div className="grid h-20 w-20 place-items-center rounded-2xl border border-cy/30 bg-bg-1/70 shadow-glow backdrop-blur">
              <Image
                src="/qos-logo-transparent.png"
                alt="QoS Buddy logo"
                width={72}
                height={72}
                priority
                className="h-16 w-16 object-contain"
              />
            </div>
            <div>
              <div className="text-xs font-medium uppercase tracking-[0.26em] text-cy">QOS-Buddy</div>
              <h1 className="mt-1 text-4xl font-semibold tracking-tight text-ink-0 md:text-5xl">
                NOC Command Center
              </h1>
            </div>
          </div>

          <div className="max-w-2xl space-y-4">
            <p className="text-lg leading-8 text-ink-1">
              Monitor live network quality, diagnose incidents with AI memory,
              approve safe optimizations, and produce executive-ready reports
              from one secure platform.
            </p>
            <div className="flex flex-wrap gap-2 text-xs font-medium">
              <span className="rounded-full border border-cy/30 bg-cy-soft px-3 py-1 text-cy">Live QoS telemetry</span>
              <span className="rounded-full border border-vio/30 bg-vio-soft px-3 py-1 text-vio">Local AI assistant</span>
              <span className="rounded-full border border-ok/30 bg-ok-soft px-3 py-1 text-ok">Keycloak secured</span>
            </div>
          </div>

          <div className="grid max-w-2xl grid-cols-1 gap-3 sm:grid-cols-2">
            <Feature icon={Activity} title="Real-time assurance" body="Delay, jitter, loss, throughput, and service health stay visible as the network changes." />
            <Feature icon={Brain} title="AI diagnosis" body="Incidents are explained with root cause context and similar historical cases." />
            <Feature icon={ShieldCheck} title="Governed actions" body="Recommendations are checked for risk, policy, reversibility, and rollback." />
            <Feature icon={FileText} title="Executive reports" body="MTTD, MTTR, service impact, actions taken, and recommendations are ready for review." />
          </div>
        </section>

        <section className="mx-auto w-full max-w-md">
          <div className="glass overflow-hidden rounded-2xl shadow-2xl">
            <div className="border-b border-line-subtle bg-bg-1/60 px-6 py-5">
              <div className="flex items-center gap-3">
                <div className="grid h-10 w-10 place-items-center rounded-lg bg-cy-soft text-cy">
                  <LockKeyhole className="h-5 w-5" />
                </div>
                <div>
                  <h2 className="text-lg font-semibold text-ink-0">Secure sign in</h2>
                  <p className="text-xs text-ink-2">Authenticated by Keycloak</p>
                </div>
              </div>
            </div>

            <div className="space-y-5 p-6">
              <p className="text-sm leading-6 text-ink-1">
                Use your NOC account to enter the platform. Your role controls
                which windows and operational actions are available.
              </p>

              <button
                type="button"
                onClick={login}
                className="group inline-flex w-full items-center justify-center gap-2 rounded-lg bg-gradient-to-r from-cy to-vio px-4 py-3 text-sm font-semibold text-bg-0 shadow-glow transition hover:opacity-95"
              >
                Sign in with Keycloak
                <ArrowRight className="h-4 w-4 transition group-hover:translate-x-0.5" />
              </button>

              <div className="rounded-lg border border-line-subtle bg-bg-2/50 p-3 text-xs leading-5 text-ink-2">
                Demo users include <span className="font-mono text-ink-1">noc-engineer</span>,
                <span className="font-mono text-ink-1"> engineer</span>, and
                <span className="font-mono text-ink-1"> admin-noc</span>.
              </div>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}

function Feature({
  icon: Icon,
  title,
  body,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  body: string;
}) {
  return (
    <div className="rounded-lg border border-line-subtle bg-bg-1/60 p-4 backdrop-blur">
      <div className="mb-2 flex items-center gap-2">
        <Icon className="h-4 w-4 text-cy" />
        <h3 className="text-sm font-semibold text-ink-0">{title}</h3>
      </div>
      <p className="text-xs leading-5 text-ink-2">{body}</p>
    </div>
  );
}
