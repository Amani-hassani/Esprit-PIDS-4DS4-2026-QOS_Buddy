import { Cell, Legend, Pie, PieChart, ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, LineChart, Line } from 'recharts';
import { PipelineStatus, Summary } from '../types';
import { StatCard } from '../components/StatCard';

const colors = ['#38bdf8', '#a78bfa', '#f59e0b', '#f43f5e', '#34d399', '#818cf8'];

export function DashboardPage({ summary, status }: { summary?: Summary; status?: PipelineStatus }) {
  const domainData = Object.entries(summary?.domain_distribution ?? {}).map(([name, value]) => ({ name, value }));

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 md:grid-cols-3 xl:grid-cols-6 gap-4">
        <StatCard title="Total Events" value={summary?.total_events ?? 0} />
        <StatCard title="Warnings" value={summary?.total_warnings ?? 0} />
        <StatCard title="Critical" value={summary?.total_critical ?? 0} />
        <StatCard title="Routed V1" value={summary?.routed_v1 ?? 0} />
        <StatCard title="Routed V2" value={summary?.routed_v2 ?? 0} />
        <StatCard title="Pipeline Status" value={status?.status ?? 'idle'} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <div className="card h-[320px]"><h3 className="mb-2 font-semibold">Severity Timeline</h3><ResponsiveContainer width="100%" height="90%"><LineChart data={summary?.severity_timeline ?? []}><XAxis dataKey="timestamp" hide /><YAxis /><Tooltip /><Legend /><Line type="monotone" dataKey="normal" stroke="#34d399" dot={false} /><Line type="monotone" dataKey="warning" stroke="#f59e0b" dot={false} /><Line type="monotone" dataKey="critical" stroke="#f43f5e" dot={false} /></LineChart></ResponsiveContainer></div>
        <div className="card h-[320px]"><h3 className="mb-2 font-semibold">Domain Distribution</h3><ResponsiveContainer width="100%" height="90%"><PieChart><Pie data={domainData} dataKey="value" nameKey="name" outerRadius={110}>{domainData.map((entry, idx) => <Cell key={entry.name} fill={colors[idx % colors.length]} />)}</Pie><Tooltip /><Legend /></PieChart></ResponsiveContainer></div>
      </div>

      <div className="card h-[320px]"><h3 className="mb-2 font-semibold">Top Anomaly Types</h3><ResponsiveContainer width="100%" height="90%"><BarChart data={summary?.top_anomaly_types ?? []}><XAxis dataKey="name" /><YAxis /><Tooltip /><Bar dataKey="count" fill="#60a5fa" /></BarChart></ResponsiveContainer></div>
    </div>
  );
}
