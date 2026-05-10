import { MonitoringEvent } from '../types';
import { DomainBadge } from './DomainBadge';
import { SeverityBadge } from './SeverityBadge';

export function EventsTable({ events, onSelect }: { events: MonitoringEvent[]; onSelect: (id: string) => void }) {
  return (
    <div className="card overflow-auto">
      <table className="table-base w-full min-w-[1080px]">
        <thead>
          <tr>
            <th>timestamp</th><th>event_id</th><th>node_id</th><th>severity</th><th>domain</th><th>reason</th><th>anomaly_type</th><th>health_score</th><th>confidence</th>
          </tr>
        </thead>
        <tbody>
          {events.map((event) => (
            <tr key={event.event_id} className="cursor-pointer border-t border-slate-800 hover:bg-slate-800/40" onClick={() => onSelect(event.event_id)}>
              <td>{event.timestamp}</td><td>{event.event_id}</td><td>{event.node_id}</td><td><SeverityBadge severity={event.severity} /></td><td><DomainBadge domain={event.domain} /></td><td className="max-w-[340px] truncate" title={event.reason}>{event.reason}</td><td>{String(event.payload.anomaly_type ?? '-')}</td><td>{String(event.payload.health_score ?? '-')}</td><td>{String(event.payload.confidence ?? '-')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
