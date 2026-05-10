import clsx from 'clsx';

const colorByDomain: Record<string, string> = {
  qos: 'bg-sky-500/20 text-sky-300',
  radio: 'bg-violet-500/20 text-violet-300',
  mixed: 'bg-indigo-500/20 text-indigo-300',
  unknown: 'bg-slate-700 text-slate-300',
};

export function DomainBadge({ domain }: { domain: string }) {
  return <span className={clsx('rounded px-2 py-1 text-xs font-semibold uppercase', colorByDomain[domain] ?? colorByDomain.unknown)}>{domain}</span>;
}
