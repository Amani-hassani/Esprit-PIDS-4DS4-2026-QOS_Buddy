import { useCallback, useMemo, useState } from 'react';
import { fetchEventDetails, fetchEvents } from '../api';
import { EventDrawer } from '../components/EventDrawer';
import { EventsTable } from '../components/EventsTable';
import { usePolling } from '../hooks/usePolling';
import { EventDetails, MonitoringEvent } from '../types';

export function EventsPage() {
  const [events, setEvents] = useState<MonitoringEvent[]>([]);
  const [details, setDetails] = useState<EventDetails>();
  const [filters, setFilters] = useState({ node_id: '', severity: '', domain: '', anomaly_type: '' });

  const load = useCallback(async () => {
    const params: Record<string, string> = { limit: '600' };
    Object.entries(filters).forEach(([k, v]) => { if (v) params[k] = v; });
    setEvents(await fetchEvents(params));
  }, [filters]);

  usePolling(load, 2000);

  const onSelect = useCallback(async (eventId: string) => {
    setDetails(await fetchEventDetails(eventId));
  }, []);

  const uniqueNodes = useMemo(() => Array.from(new Set(events.map((e) => e.node_id))).slice(0, 50), [events]);

  return (
    <div className="space-y-4">
      <div className="card grid grid-cols-1 md:grid-cols-4 gap-3">
        <select className="bg-slate-800 rounded px-3 py-2" value={filters.node_id} onChange={(e) => setFilters((p) => ({ ...p, node_id: e.target.value }))}><option value="">All nodes</option>{uniqueNodes.map((n) => <option key={n} value={n}>{n}</option>)}</select>
        <select className="bg-slate-800 rounded px-3 py-2" value={filters.severity} onChange={(e) => setFilters((p) => ({ ...p, severity: e.target.value }))}><option value="">All severities</option><option value="normal">normal</option><option value="warning">warning</option><option value="critical">critical</option></select>
        <select className="bg-slate-800 rounded px-3 py-2" value={filters.domain} onChange={(e) => setFilters((p) => ({ ...p, domain: e.target.value }))}><option value="">All domains</option><option value="qos">qos</option><option value="radio">radio</option><option value="mixed">mixed</option><option value="unknown">unknown</option></select>
        <input className="bg-slate-800 rounded px-3 py-2" placeholder="anomaly_type" value={filters.anomaly_type} onChange={(e) => setFilters((p) => ({ ...p, anomaly_type: e.target.value }))} />
      </div>
      <EventsTable events={events} onSelect={onSelect} />
      <EventDrawer details={details} onClose={() => setDetails(undefined)} />
    </div>
  );
}
