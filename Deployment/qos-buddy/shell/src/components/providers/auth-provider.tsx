"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import type Keycloak from "keycloak-js";
import { ShieldAlert } from "lucide-react";
import { getKeycloak, selectRole, type Role } from "@/lib/keycloak";

const DEMO_MODE = process.env.NEXT_PUBLIC_DEMO_MODE === "true";
const DEMO_ROLES: Role[] = ["noc_viewer", "noc_executive", "ai_engineer", "site_admin"];
const DEMO_STORAGE_KEY = "qos-demo-role";
const GATEWAY_URL = process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:8080";

export interface UserPreferences {
  preferred_page?: string;
  alert_filter?: "info" | "low" | "medium" | "high" | "critical";
  cell_focus?: string[];
}

export interface AuthState {
  ready: boolean;
  authenticated: boolean;
  username: string;
  email: string | null;
  role: Role;
  token: string | null;
  demoMode: boolean;
  preferences: UserPreferences;
  setDemoRole?: (r: Role) => void;
  login: () => void;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

function usePreferenceSync({
  ready,
  authenticated,
  token,
}: {
  ready: boolean;
  authenticated: boolean;
  token: string | null;
}) {
  const pathname = usePathname();
  const [preferences, setPreferences] = useState<UserPreferences>({});

  useEffect(() => {
    if (!ready || !authenticated || !token) return;
    let cancelled = false;
    fetch(`${GATEWAY_URL}/api/memory/preference/me`, {
      headers: { authorization: `Bearer ${token}` },
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((data: { preferences?: UserPreferences } | null) => {
        if (!cancelled) setPreferences(normalizePreferences(data?.preferences));
      })
      .catch(() => {
        if (!cancelled) setPreferences({});
      });
    return () => {
      cancelled = true;
    };
  }, [ready, authenticated, token]);

  useEffect(() => {
    if (!ready || !authenticated || !token || !pathname) return;
    fetch(`${GATEWAY_URL}/api/memory/preference`, {
      method: "POST",
      headers: {
        authorization: `Bearer ${token}`,
        "content-type": "application/json",
      },
      body: JSON.stringify({ preference_type: "preferred_page", value: pathname }),
    }).catch(() => {});
  }, [ready, authenticated, token, pathname]);

  return preferences;
}

function normalizePreferences(raw: UserPreferences | undefined): UserPreferences {
  if (!raw) return {};
  return {
    preferred_page: typeof raw.preferred_page === "string" ? raw.preferred_page : undefined,
    alert_filter: isSeverity(raw.alert_filter) ? raw.alert_filter : undefined,
    cell_focus: Array.isArray(raw.cell_focus)
      ? raw.cell_focus.filter((cell): cell is string => typeof cell === "string")
      : undefined,
  };
}

function isSeverity(value: unknown): value is UserPreferences["alert_filter"] {
  return (
    value === "info" ||
    value === "low" ||
    value === "medium" ||
    value === "high" ||
    value === "critical"
  );
}

// ─── Demo-mode provider (no Keycloak) ────────────────────────────────────────

function DemoAuthProvider({ children }: { children: React.ReactNode }) {
  const [role, setRole] = useState<Role>(() => {
    if (typeof window === "undefined") return "noc_executive";
    const stored = sessionStorage.getItem(DEMO_STORAGE_KEY) as Role | null;
    return !stored || stored === "noc_viewer" ? "noc_executive" : stored;
  });
  const preferences = usePreferenceSync({
    ready: true,
    authenticated: true,
    token: `demo:${role}`,
  });

  const setDemoRole = useCallback((r: Role) => {
    setRole(r);
    sessionStorage.setItem(DEMO_STORAGE_KEY, r);
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      ready: true,
      authenticated: true,
      username: "demo-user",
      email: null,
      role,
      token: null,
      demoMode: true,
      preferences,
      setDemoRole,
      login: () => {},
      logout: () => setDemoRole("noc_executive"),
    }),
    [role, preferences, setDemoRole],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// ─── Keycloak provider (production) ──────────────────────────────────────────

function KeycloakAuthProvider({ children }: { children: React.ReactNode }) {
  const [kc, setKc] = useState<Keycloak | null>(null);
  const [ready, setReady] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const [token, setToken] = useState<string | null>(null);

  useEffect(() => {
    const instance = getKeycloak();
    let cancelled = false;
    instance
      .init({
        onLoad: "check-sso",
        pkceMethod: "S256",
        checkLoginIframe: false,
        enableLogging: process.env.NODE_ENV !== "production",
      })
      .then((auth) => {
        if (cancelled) return;
        setKc(instance);
        setAuthenticated(auth);
        setToken(instance.token ?? null);
        setReady(true);
      })
      .catch(() => {
        if (cancelled) return;
        setReady(true);
        setAuthenticated(false);
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!kc || !authenticated) return;
    const id = window.setInterval(() => {
      kc.updateToken(60)
        .then((refreshed) => { if (refreshed) setToken(kc.token ?? null); })
        .catch(() => { setAuthenticated(false); setToken(null); });
    }, 30_000);
    return () => window.clearInterval(id);
  }, [kc, authenticated]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (token) {
      window.sessionStorage.setItem("qos-auth-token", token);
    } else {
      window.sessionStorage.removeItem("qos-auth-token");
    }
  }, [token]);

  const role = useMemo<Role>(
    () => selectRole(kc?.tokenParsed?.["realm_access"]?.roles as string[] | undefined),
    [kc, token],
  );
  const preferences = usePreferenceSync({ ready, authenticated, token });

  const login = useCallback(() => kc?.login(), [kc]);
  const logout = useCallback(() => {
    window.sessionStorage.removeItem("qos-auth-token");
    kc?.logout({ redirectUri: window.location.origin });
  }, [kc]);

  const value: AuthState = {
    ready,
    authenticated,
    username: (kc?.tokenParsed?.["preferred_username"] as string | undefined) ?? "",
    email: (kc?.tokenParsed?.["email"] as string | undefined) ?? null,
    role,
    token,
    demoMode: false,
    preferences,
    login,
    logout,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// ─── Public export ────────────────────────────────────────────────────────────

export function AuthProvider({ children }: { children: React.ReactNode }) {
  if (DEMO_MODE) return <DemoAuthProvider>{children}</DemoAuthProvider>;
  return <KeycloakAuthProvider>{children}</KeycloakAuthProvider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

export function Redirect403() {
  const { role } = useAuth();

  return (
    <div className="grid min-h-[calc(100vh-8rem)] place-items-center">
      <div className="glass max-w-md rounded-xl border border-warn/30 p-6 text-center">
        <ShieldAlert className="mx-auto h-8 w-8 text-warn" />
        <h1 className="mt-3 text-lg font-semibold text-ink-0">Access restricted</h1>
        <p className="mt-2 text-sm text-ink-2">
          Your current role is <span className="font-mono text-ink-1">{role}</span>.
          This area requires a higher access level.
        </p>
        <Link
          href="/"
          className="mt-4 inline-flex rounded-lg bg-cy px-4 py-2 text-sm font-medium text-bg-0 transition hover:opacity-90"
        >
          Back to Command Center
        </Link>
      </div>
    </div>
  );
}

export function RoleGate({
  allow,
  children,
  fallback,
}: {
  allow: Role[];
  children: React.ReactNode;
  fallback?: React.ReactNode;
}) {
  const { role, ready } = useAuth();
  if (!ready) return null;
  if (!allow.includes(role)) return fallback ?? <Redirect403 />;
  return <>{children}</>;
}

export { DEMO_ROLES };
