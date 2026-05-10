import { useCallback, useState } from 'react';
import { fetchRawLogs } from '../api';
import { usePolling } from '../hooks/usePolling';

function LogPanel({ title, lines }: { title: string; lines: string[] }) {
  return (
    <div className="card">
      <h3 className="mb-2 font-semibold">{title}</h3>
      <div className="h-[280px] overflow-auto rounded bg-slate-950 p-3 font-mono text-xs text-slate-200 whitespace-pre-wrap">
        {lines.length ? lines.join('\n') : 'No data yet'}
      </div>
    </div>
  );
}

export function LogsPage() {
  const [logs, setLogs] = useState<Record<string, string[]>>({});
  const load = useCallback(async () => setLogs(await fetchRawLogs()), []);
  usePolling(load, 2000);

  return (
    <div className="space-y-4">
      <LogPanel title="network_stream.jsonl" lines={logs.network_stream ?? []} />
      <LogPanel title="monitoring_events.jsonl" lines={logs.monitoring_events ?? []} />
      <LogPanel title="workflow_actions.jsonl" lines={logs.workflow_actions ?? []} />
    </div>
  );
}
