import { Action } from '../types';
import { DomainBadge } from './DomainBadge';

export function ActionsTable({ actions }: { actions: Action[] }) {
  return (
    <div className="card overflow-auto">
      <table className="table-base w-full min-w-[900px]">
        <thead><tr><th>version</th><th>event_id</th><th>status</th><th>targets</th><th>domain</th><th>priority</th><th>graph_score</th></tr></thead>
        <tbody>
          {actions.map((a, idx) => (
            <tr key={`${a.version}-${a.event_id}-${idx}`} className="border-t border-slate-800">
              <td>{a.version}</td><td>{a.event_id}</td><td>{a.status}</td><td>{a.targets.join(', ') || '-'}</td><td><DomainBadge domain={a.domain} /></td><td>{a.priority}</td><td>{a.graph_score ?? '-'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
