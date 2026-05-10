"use client";

import { Construction } from "lucide-react";

interface PageStubProps {
  title: string;
  description: string;
  comingNext: string[];
}

export function PageStub({ title, description, comingNext }: PageStubProps) {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        <p className="text-sm text-ink-2">{description}</p>
      </header>
      <div className="glass rounded-xl p-6">
        <div className="flex items-start gap-3">
          <span className="grid h-9 w-9 place-items-center rounded-lg bg-warn-soft text-warn">
            <Construction className="h-4 w-4" />
          </span>
          <div>
            <div className="font-medium">Wired in the next iteration</div>
            <p className="mt-1 text-sm text-ink-2">
              The data path is already live; this view is being assembled. The
              stream is flowing into the dashboard — we just haven&rsquo;t
              rendered it here yet.
            </p>
            <ul className="mt-3 list-inside list-disc space-y-1 text-sm text-ink-1">
              {comingNext.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}
