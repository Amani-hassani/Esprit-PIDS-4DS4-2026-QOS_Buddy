"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import * as Dialog from "@radix-ui/react-dialog";
import {
  Activity,
  AlertTriangle,
  Brain,
  ClipboardList,
  Compass,
  FileText,
  Gauge,
  Menu,
  ShieldCheck,
  SlidersHorizontal,
  TrendingUp,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/components/providers/auth-provider";

interface NavItem {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  // Roles allowed to see this item. Undefined = everyone.
  roles?: ReadonlyArray<"noc_viewer" | "noc_executive" | "ai_engineer" | "site_admin">;
}

const NAV: NavItem[] = [
  { href: "/", label: "Command Center", icon: Gauge },
  { href: "/detection-prediction", label: "Detection", icon: Activity },
  { href: "/forecast", label: "Forecast", icon: TrendingUp },
  { href: "/diagnostic", label: "Diagnostic", icon: Compass },
  { href: "/optimization", label: "Optimization", icon: ShieldCheck },
  { href: "/reporting", label: "Reporting", icon: FileText },
  {
    href: "/audit",
    label: "Audit Log",
    icon: ClipboardList,
    roles: ["noc_executive", "ai_engineer", "site_admin"],
  },
  {
    href: "/ai-lab",
    label: "AI Lab",
    icon: Brain,
    roles: ["site_admin", "ai_engineer"],
  },
  {
    href: "/what-if",
    label: "What-If",
    icon: SlidersHorizontal,
    roles: ["noc_executive", "site_admin", "ai_engineer"],
  },
];

export function Sidebar() {
  return (
    <aside className="hidden w-60 shrink-0 flex-col border-r border-line-subtle bg-bg-1/60 backdrop-blur lg:flex">
      <SidebarContent />
    </aside>
  );
}

export function MobileSidebarButton() {
  return (
    <Dialog.Root>
      <Dialog.Trigger asChild>
        <button
          type="button"
          className="grid h-9 w-9 place-items-center rounded-lg border border-line-subtle bg-bg-2 text-ink-1 transition hover:bg-bg-3 hover:text-ink-0 lg:hidden"
          aria-label="Open navigation"
        >
          <Menu className="h-4 w-4" />
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm lg:hidden" />
        <Dialog.Content className="fixed inset-y-0 left-0 z-50 flex w-72 max-w-[85vw] flex-col border-r border-line-subtle bg-bg-1 shadow-xl lg:hidden">
          <div className="absolute right-3 top-3">
            <Dialog.Close asChild>
              <button
                type="button"
                className="grid h-8 w-8 place-items-center rounded-lg border border-line-subtle bg-bg-2 text-ink-1"
                aria-label="Close navigation"
              >
                <X className="h-4 w-4" />
              </button>
            </Dialog.Close>
          </div>
          <SidebarContent closeOnNavigate />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function SidebarContent({ closeOnNavigate = false }: { closeOnNavigate?: boolean }) {
  const pathname = usePathname();
  const { role } = useAuth();

  return (
    <>
      <div className="flex h-16 items-center gap-2 border-b border-line-subtle px-4">
        <div className="relative h-10 w-10 shrink-0 overflow-hidden rounded-lg bg-bg-0 shadow-glow">
          <Image
            src="/logo.png"
            alt="QOS-Buddy"
            width={40}
            height={40}
            priority
            className="h-full w-full object-cover"
          />
        </div>
        <div className="leading-tight">
          <div className="text-sm font-semibold tracking-wide">QOS-Buddy</div>
          <div className="text-xs text-ink-2">NOC Command Center</div>
        </div>
      </div>

      <nav className="flex-1 space-y-1 px-3 py-4">
        {NAV.filter((n) => !n.roles || n.roles.includes(role)).map((item) => {
          const active =
            item.href === "/"
              ? pathname === "/"
              : pathname.startsWith(item.href);
          const Icon = item.icon;
          const link = (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "group flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition",
                active
                  ? "bg-cy-soft text-cy"
                  : "text-ink-1 hover:bg-bg-2 hover:text-ink-0",
              )}
            >
              <Icon
                className={cn(
                  "h-4 w-4",
                  active ? "text-cy" : "text-ink-2 group-hover:text-ink-0",
                )}
              />
              <span className="font-medium">{item.label}</span>
              {active && (
                <span className="ml-auto h-1.5 w-1.5 rounded-full bg-cy shadow-glow" />
              )}
            </Link>
          );
          return closeOnNavigate ? (
            <Dialog.Close key={item.href} asChild>
              {link}
            </Dialog.Close>
          ) : link;
        })}
      </nav>

      <div className="border-t border-line-subtle p-3">
        <div className="rounded-lg border border-line-subtle bg-bg-2/60 p-3 text-xs">
          <div className="mb-1 flex items-center gap-2 text-ink-2">
            <AlertTriangle className="h-3.5 w-3.5 text-warn" />
            <span>Supervised live mode</span>
          </div>
          <p className="text-ink-1 leading-relaxed">
            Live telemetry and agent decisions are active. Remediation still
            requires operator approval.
          </p>
        </div>
      </div>
    </>
  );
}
