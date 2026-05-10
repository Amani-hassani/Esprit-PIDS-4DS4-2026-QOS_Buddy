import { EventDetails } from '../types';
import { DomainBadge } from './DomainBadge';
import { SeverityBadge } from './SeverityBadge';

export function EventDrawer({ details, onClose }: { details?: EventDetails; onClose: () => void }) {
  if (!details) return null;

  return (
    <div className="fixed inset-0 z-50 bg-black/70">
      <div className="absolute right-0 top-0 h-full w-[680px] overflow-auto border-l border-slate-700 bg-slate-900 p-5">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Event Details - {details.event.event_id}</h2>
          <button onClick={onClose} className="rounded bg-slate-800 px-3 py-1 text-sm">Close</button>
        </div>

        <div className="space-y-4 text-sm">
          <p><strong>Timestamp:</strong> {details.event.timestamp}</p>
          <p><strong>Node:</strong> {details.event.node_id}</p>
          <p><strong>Reason:</strong> {details.event.reason}</p>
          <div className="flex gap-2"><SeverityBadge severity={details.event.severity} /><DomainBadge domain={details.event.domain} /></div>

          <div>
            <h3 className="font-semibold">Action V1</h3>
            <pre className="mt-1 overflow-auto rounded bg-slate-950 p-3 text-xs">{JSON.stringify(details.action_v1 ?? null, null, 2)}</pre>
          </div>

          <div>
            <h3 className="font-semibold">Action V2 GNN</h3>
            <pre className="mt-1 overflow-auto rounded bg-slate-950 p-3 text-xs">{JSON.stringify(details.action_v2_gnn ?? null, null, 2)}</pre>
          </div>

          <div>
            <h3 className="font-semibold">Payload</h3>
            <pre className="mt-1 overflow-auto rounded bg-slate-950 p-3 text-xs">{JSON.stringify(details.event.payload, null, 2)}</pre>
          </div>
        </div>
      </div>
    </div>
  );
}
