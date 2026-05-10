import clsx from 'clsx';

export function SeverityBadge({ severity }: { severity: string }) {
  return (
    <span className={clsx('rounded px-2 py-1 text-xs font-semibold uppercase', {
      'bg-emerald-500/20 text-emerald-300': severity === 'normal',
      'bg-amber-500/20 text-amber-300': severity === 'warning',
      'bg-rose-500/20 text-rose-300': severity === 'critical',
      'bg-slate-700 text-slate-300': !['normal', 'warning', 'critical'].includes(severity),
    })}>
      {severity}
    </span>
  );
}
