"use client";

export function EmptyState({
  icon,
  title,
  body,
}: {
  icon: React.ReactNode;
  title: string;
  body: string;
}) {
  return (
    <div className="grid place-items-center rounded-lg border border-dashed border-line-subtle p-8 text-center">
      <div className="flex max-w-sm flex-col items-center gap-2">
        {icon}
        <h3 className="text-sm font-medium text-ink-1">{title}</h3>
        <p className="text-sm leading-relaxed text-ink-2">{body}</p>
      </div>
    </div>
  );
}
