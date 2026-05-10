"use client";

import { useTheme } from "next-themes";
import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  ChevronDown,
  CircuitBoard,
  KeyRound,
  LogOut,
  Mic,
  MicOff,
  Moon,
  Sun,
  Wifi,
  WifiOff,
} from "lucide-react";
import { useAuth, DEMO_ROLES } from "@/components/providers/auth-provider";
import { useLive } from "@/lib/store";
import { cn } from "@/lib/utils";
import { askAi } from "@/lib/ai";
import { TimeToBreach } from "./time-to-breach";
import { MobileSidebarButton } from "./sidebar";
import { useNotifications } from "@/components/ui/notifications";
import type { Role } from "@/lib/keycloak";

const ROLE_LABEL: Record<Role, string> = {
  noc_viewer: "NOC Viewer",
  noc_executive: "NOC Engineer",
  ai_engineer: "AI Engineer",
  site_admin: "Site Admin",
};

export function Topbar() {
  const { theme, setTheme, resolvedTheme } = useTheme();
  const { username, role, logout, ready, authenticated, demoMode } = useAuth();
  const connected = useLive((s) => s.connected);
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);
  const dark = mounted ? (resolvedTheme ?? theme) === "dark" : false;

  return (
    <header className="sticky top-0 z-30 flex h-16 items-center gap-4 border-b border-line-subtle bg-bg-1/80 px-4 backdrop-blur">
      <MobileSidebarButton />
      <div className="flex items-center gap-2 text-sm">
        <CircuitBoard className="h-4 w-4 text-cy" />
        <span className="font-medium">Live Network</span>
        <ConnectionPill connected={connected} authenticated={authenticated} ready={ready} />
      </div>

      <TimeToBreach />

      <div className="ml-auto flex items-center gap-2">
        <VoiceButton />

        <button
          type="button"
          onClick={() => setTheme(dark ? "light" : "dark")}
          className="grid h-9 w-9 place-items-center rounded-lg border border-line-subtle bg-bg-2 text-ink-1 transition hover:bg-bg-3 hover:text-ink-0"
          aria-label="Toggle theme"
          title={dark ? "Switch to light" : "Switch to dark"}
        >
          {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </button>

        {demoMode ? (
          <DemoRoleSwitcher role={role} />
        ) : (
          <div className="hidden md:flex items-center gap-2 rounded-lg border border-line-subtle bg-bg-2 px-3 py-1.5 text-sm">
            <span className="text-ink-2">{ROLE_LABEL[role] ?? role}</span>
            <span className="h-1 w-1 rounded-full bg-ink-3" />
            <span className="font-medium">{username || "—"}</span>
            <KeyRound className="h-3.5 w-3.5 text-ok" />
            <ChevronDown className="h-3.5 w-3.5 text-ink-2" />
          </div>
        )}

        <button
          type="button"
          onClick={logout}
          className="grid h-9 w-9 place-items-center rounded-lg border border-line-subtle bg-bg-2 text-ink-1 transition hover:bg-bad-soft hover:text-bad"
          aria-label="Sign out"
          title="Sign out"
        >
          <LogOut className="h-4 w-4" />
        </button>
      </div>
    </header>
  );
}

function DemoRoleSwitcher({ role }: { role: Role }) {
  const { setDemoRole } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 rounded-lg border border-line-subtle bg-bg-2 px-3 py-1.5 text-sm transition hover:bg-bg-3"
        title="Switch demo role"
      >
        <span className="text-ink-2">Role</span>
        <span className="h-1 w-1 rounded-full bg-ink-3" />
        <span className="font-medium">{ROLE_LABEL[role]}</span>
        <ChevronDown className={cn("h-3.5 w-3.5 text-ink-2 transition-transform", open && "rotate-180")} />
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 z-50 min-w-[180px] overflow-hidden rounded-lg border border-line-subtle bg-bg-1 shadow-xl">
          {DEMO_ROLES.map((r) => (
            <button
              key={r}
              type="button"
              onClick={() => { setDemoRole?.(r); setOpen(false); }}
              className={cn(
                "flex w-full items-center gap-2 px-3 py-2 text-sm text-left transition hover:bg-bg-2",
                r === role ? "text-cy font-medium" : "text-ink-1",
              )}
            >
              {r === role && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-cy" />}
              {r !== role && <span className="h-1.5 w-1.5 shrink-0" />}
              {ROLE_LABEL[r]}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function ConnectionPill({
  connected,
  authenticated,
  ready,
}: {
  connected: boolean;
  authenticated: boolean;
  ready: boolean;
}) {
  let label = "Offline";
  let tone = "bad";
  let Icon = WifiOff;
  if (!ready) {
    label = "Connecting…";
    tone = "info";
    Icon = Wifi;
  } else if (!authenticated) {
    label = "Sign in required";
    tone = "warn";
  } else if (connected) {
    label = "Live collector";
    tone = "ok";
    Icon = Wifi;
  } else {
    label = "Reconnecting…";
    tone = "warn";
  }
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium",
        tone === "ok" && "bg-ok-soft text-ok",
        tone === "warn" && "bg-warn-soft text-warn",
        tone === "info" && "bg-info-soft text-info",
        tone === "bad" && "bg-bad-soft text-bad",
      )}
    >
      <Icon className="h-3 w-3" />
      {label}
    </span>
  );
}

// ─── Voice command button (Sprint J) ─────────────────────────────────────────

const VOICE_ROUTES: Array<{ keywords: string[]; route: string; label: string }> = [
  { keywords: ["command center", "home", "dashboard", "overview"],      route: "/",                    label: "Command Center" },
  { keywords: ["detection", "anomaly", "anomalies", "alerts"],          route: "/detection-prediction", label: "Detection" },
  { keywords: ["forecast", "prediction", "predict"],                    route: "/forecast",             label: "Forecast" },
  { keywords: ["diagnostic", "diagnosis", "root cause", "root-cause"],  route: "/diagnostic",          label: "Diagnostic" },
  { keywords: ["optimization", "optimise", "optimize", "remediation"],  route: "/optimization",        label: "Optimization" },
  { keywords: ["report", "reporting", "post-mortem", "postmortem"],     route: "/reporting",           label: "Reporting" },
  { keywords: ["audit", "audit log", "history"],                        route: "/audit",               label: "Audit Log" },
  { keywords: ["ai lab", "lab", "ai-lab", "pipeline"],                  route: "/ai-lab",              label: "AI Lab" },
  { keywords: ["what if", "what-if", "sandbox", "scenario"],           route: "/what-if",             label: "What-If" },
];

function matchRoute(transcript: string): { route: string; label: string } | null {
  const lower = transcript.toLowerCase();
  for (const { keywords, route, label } of VOICE_ROUTES) {
    if (keywords.some((k) => lower.includes(k))) return { route, label };
  }
  return null;
}

const QUESTION_PREFIXES = [
  "what",
  "how",
  "why",
  "when",
  "which",
  "who",
  "tell me",
  "show me",
  "find",
];

function matchQuery(transcript: string): boolean {
  const lower = transcript.trim().toLowerCase();
  return QUESTION_PREFIXES.some((prefix) => lower.startsWith(prefix));
}

function VoiceButton() {
  const router = useRouter();
  const pathname = usePathname();
  const { role } = useAuth();
  const pushToast = useNotifications((s) => s.push);
  const [listening, setListening] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [supported, setSupported] = useState(false);
  const [thinking, setThinking] = useState(false);
  const recogRef = useRef<any>(null);

  useEffect(() => {
    setSupported(!!((window as any).SpeechRecognition || (window as any).webkitSpeechRecognition));
  }, []);

  function showToast(msg: string, duration = 3000, tone: "info" | "ok" | "warn" = "info") {
    pushToast({ message: msg, tone, duration });
  }

  async function handleQuery(raw: string) {
    setThinking(true);
    showToast("Thinking — searching operator memory…", 2000);
    const answer = await askAi(
      raw,
      { current_page: pathname, role },
      "No matching lesson found in operator memory.",
    );
    setThinking(false);
    showToast(answer, 8000, "ok");
    if (typeof window !== "undefined" && window.speechSynthesis) {
      window.speechSynthesis.cancel();
      const utt = new SpeechSynthesisUtterance(answer);
      utt.rate = 0.98;
      utt.pitch = 1.0;
      window.speechSynthesis.speak(utt);
    }
  }

  function startListening() {
    const SR = (window as any).SpeechRecognition ?? (window as any).webkitSpeechRecognition;
    if (!SR) return;
    const recog = new SR();
    recog.lang = "en-US";
    recog.continuous = false;
    recog.interimResults = true;
    recogRef.current = recog;

    recog.onresult = (e: any) => {
      const raw = Array.from(e.results as any[])
        .map((r: any) => r[0].transcript)
        .join(" ");
      setTranscript(raw);
      if (e.results[0].isFinal) {
        const match = matchRoute(raw);
        if (match) {
          showToast(`Navigating to ${match.label}…`);
          router.push(match.route);
        } else if (matchQuery(raw)) {
          void handleQuery(raw);
        } else {
          showToast(`No route matched: "${raw}"`);
        }
      }
    };

    recog.onend = () => {
      setListening(false);
      setTranscript("");
    };

    recog.onerror = () => {
      setListening(false);
      setTranscript("");
    };

    setListening(true);
    recog.start();
  }

  function stopListening() {
    recogRef.current?.stop();
    setListening(false);
    setTranscript("");
  }

  if (!supported) return null;

  const active = listening || thinking;

  return (
    <div className="relative">
      <button
        type="button"
        onClick={listening ? stopListening : startListening}
        title={
          thinking
            ? "Querying operator memory…"
            : listening
              ? "Stop voice command"
              : "Voice command — say a page name or ask a question"
        }
        className={cn(
          "relative grid h-9 w-9 place-items-center rounded-lg border transition",
          active
            ? "border-cy bg-cy-soft text-cy"
            : "border-line-subtle bg-bg-2 text-ink-1 hover:bg-bg-3 hover:text-ink-0",
        )}
      >
        {active ? <Mic className="h-4 w-4" /> : <MicOff className="h-4 w-4" />}
        {listening && (
          <span className="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full border-2 border-bg-1 bg-bad animate-pulse" />
        )}
        {thinking && !listening && (
          <span className="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full border-2 border-bg-1 bg-vio animate-pulse" />
        )}
      </button>

      {listening && transcript && (
        <div className="absolute right-0 top-full mt-1.5 z-50 max-w-xs rounded-lg border border-cy/40 bg-bg-1 px-3 py-2 shadow-xl">
          <p className="text-xs italic text-ink-1">&ldquo;{transcript}&rdquo;</p>
        </div>
      )}
    </div>
  );
}
