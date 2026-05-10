"use client";

import { create } from "zustand";
import { cn } from "@/lib/utils";

interface Toast {
  id: string;
  message: string;
  tone: "ok" | "warn" | "bad" | "info";
  duration?: number;
}

export const useNotifications = create<{
  toasts: Toast[];
  push: (t: Omit<Toast, "id">) => void;
  dismiss: (id: string) => void;
}>((set, get) => ({
  toasts: [],
  push: (toast) => {
    const id = `toast-${Date.now()}-${get().toasts.length}`;
    set((state) => ({ toasts: [...state.toasts, { ...toast, id }] }));
    window.setTimeout(() => get().dismiss(id), toast.duration ?? 3000);
  },
  dismiss: (id) =>
    set((state) => ({ toasts: state.toasts.filter((toast) => toast.id !== id) })),
}));

const TONE_CLASS: Record<Toast["tone"], string> = {
  ok: "border-ok/40 bg-ok-soft text-ok",
  warn: "border-warn/40 bg-warn-soft text-warn",
  bad: "border-bad/40 bg-bad-soft text-bad",
  info: "border-cy/40 bg-bg-1 text-ink-1",
};

export function NotificationStack() {
  const toasts = useNotifications((s) => s.toasts);
  const dismiss = useNotifications((s) => s.dismiss);

  return (
    <div className="fixed bottom-4 right-4 z-[100] flex w-[min(22rem,calc(100vw-2rem))] flex-col gap-2">
      {toasts.map((toast) => (
        <button
          key={toast.id}
          type="button"
          onClick={() => dismiss(toast.id)}
          className={cn(
            "rounded-lg border px-3 py-2 text-left text-xs font-medium shadow-xl backdrop-blur transition hover:opacity-90",
            TONE_CLASS[toast.tone],
          )}
        >
          {toast.message}
        </button>
      ))}
    </div>
  );
}
