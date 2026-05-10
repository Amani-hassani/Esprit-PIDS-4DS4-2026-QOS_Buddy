"use client";

import { ThemeProvider as NextThemesProvider } from "next-themes";
import { useAuth } from "./auth-provider";
import { useEffect } from "react";

/**
 * Wraps next-themes with a sensible per-role default:
 *   • NOC Executive  → light  (boardroom briefing)
 *   • everyone else  → dark   (NOC vibe)
 *
 * The user can override; the default only kicks in on first visit.
 */
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  return (
    <NextThemesProvider
      attribute="class"
      defaultTheme="dark"
      enableSystem={false}
      storageKey="qos-theme"
    >
      <RoleDefault />
      {children}
    </NextThemesProvider>
  );
}

function RoleDefault() {
  const { role, ready } = useAuth();

  useEffect(() => {
    if (!ready) return;
    if (typeof window === "undefined") return;
    const explicit = window.localStorage.getItem("qos-theme:user-set");
    if (explicit === "1") return;

    const desired = role === "noc_executive" ? "light" : "dark";
    if (window.localStorage.getItem("qos-theme") !== desired) {
      window.localStorage.setItem("qos-theme", desired);
      document.documentElement.classList.toggle("dark", desired === "dark");
    }
  }, [role, ready]);

  return null;
}
