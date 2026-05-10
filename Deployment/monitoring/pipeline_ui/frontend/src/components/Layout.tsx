import { NavLink, Outlet } from 'react-router-dom';
import { PipelineStatus } from '../types';

const links = [
  { to: '/', label: 'Dashboard' },
  { to: '/events', label: 'Live Events' },
  { to: '/actions', label: 'Workflow Actions' },
  { to: '/logs', label: 'Logs / Raw Stream' },
];

export function Layout({ status, apiConnected }: { status?: PipelineStatus; apiConnected: boolean }) {
  return (
    <div className="min-h-screen grid grid-cols-[240px_1fr]">
      <aside className="border-r border-slate-800 bg-slate-900 p-4">
        <h1 className="text-lg font-bold">Pipeline UI</h1>
        <nav className="mt-5 space-y-2">
          {links.map((link) => (
            <NavLink key={link.to} to={link.to} className={({ isActive }) => `block rounded px-3 py-2 text-sm ${isActive ? 'bg-slate-700 text-white' : 'text-slate-300 hover:bg-slate-800'}`}>
              {link.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main>
        <header className="flex items-center justify-between border-b border-slate-800 bg-slate-900/70 px-6 py-3">
          <p className="text-sm text-slate-300">Real-time monitoring and workflow comparison</p>
          <div className="flex items-center gap-2">
            <span className={`rounded px-2 py-1 text-xs font-semibold ${status?.status === 'live' ? 'bg-emerald-500/20 text-emerald-300' : status?.status === 'stale' ? 'bg-amber-500/20 text-amber-300' : 'bg-slate-700 text-slate-300'}`}>
              {status?.status ?? 'idle'}
            </span>
            <span className={`rounded px-2 py-1 text-xs font-semibold ${apiConnected ? 'bg-emerald-500/20 text-emerald-300' : 'bg-rose-500/20 text-rose-300'}`}>
              {apiConnected ? 'api connected' : 'api disconnected'}
            </span>
          </div>
        </header>
        <div className="p-6"><Outlet /></div>
      </main>
    </div>
  );
}
