import { useCallback, useMemo, useState } from 'react';
import { fetchActionComparison, fetchActions } from '../api';
import { ActionsTable } from '../components/ActionsTable';
import { usePolling } from '../hooks/usePolling';
import { Action } from '../types';

export function ActionsPage() {
  const [actions, setActions] = useState<Action[]>([]);
  const [comparison, setComparison] = useState<Array<{ event_id: string; v1?: Action; v2_gnn?: Action }>>([]);
  const [filters, setFilters] = useState({ version: '', domain: '', event_id: '' });

  const load = useCallback(async () => {
    const params: Record<string, string> = { limit: '700' };
    Object.entries(filters).forEach(([k, v]) => { if (v) params[k] = v; });
    const [actionsData, compData] = await Promise.all([fetchActions(params), fetchActionComparison()]);
    setActions(actionsData);
    setComparison(compData);
  }, [filters]);

  usePolling(load, 2000);
  const rows = useMemo(() => comparison.slice(0, 80), [comparison]);

  return (
    <div className="space-y-4">
      <div className="card grid grid-cols-1 md:grid-cols-3 gap-3">
        <select className="bg-slate-800 rounded px-3 py-2" value={filters.version} onChange={(e) => setFilters((p) => ({ ...p, version: e.target.value }))}><option value="">All versions</option><option value="v1">v1</option><option value="v2_gnn">v2_gnn</option></select>
        <select className="bg-slate-800 rounded px-3 py-2" value={filters.domain} onChange={(e) => setFilters((p) => ({ ...p, domain: e.target.value }))}><option value="">All domains</option><option value="qos">qos</option><option value="radio">radio</option><option value="mixed">mixed</option><option value="unknown">unknown</option></select>
        <input className="bg-slate-800 rounded px-3 py-2" placeholder="event_id" value={filters.event_id} onChange={(e) => setFilters((p) => ({ ...p, event_id: e.target.value }))} />
      </div>
      <ActionsTable actions={actions} />
      <div className="card overflow-auto"><h3 className="mb-3 text-sm font-semibold text-slate-200">V1 vs V2 Comparison</h3><table className="table-base w-full min-w-[1080px]"><thead><tr><th>event_id</th><th>V1 status</th><th>V1 targets</th><th>V2 status</th><th>V2 targets</th><th>V2 graph_score</th><th>domain</th><th>priority</th></tr></thead><tbody>{rows.map((row) => (<tr key={row.event_id} className="border-t border-slate-800"><td>{row.event_id}</td><td>{row.v1?.status ?? '-'}</td><td>{row.v1?.targets?.join(', ') ?? '-'}</td><td>{row.v2_gnn?.status ?? '-'}</td><td>{row.v2_gnn?.targets?.join(', ') ?? '-'}</td><td>{row.v2_gnn?.graph_score ?? '-'}</td><td>{row.v2_gnn?.domain ?? row.v1?.domain ?? '-'}</td><td>{row.v2_gnn?.priority ?? row.v1?.priority ?? '-'}</td></tr>))}</tbody></table></div>
    </div>
  );
}
