export type Severity = 'normal' | 'warning' | 'critical' | 'unknown';

export interface MonitoringEvent {
  event_id: string;
  event_type: string;
  timestamp: string;
  node_id: string;
  severity: Severity;
  reason: string;
  domain: string;
  payload: Record<string, unknown>;
}

export interface Action {
  version: 'v1' | 'v2_gnn';
  event_id: string;
  status: string;
  targets: string[];
  domain: string;
  priority: string;
  graph_score?: number;
  message?: string;
  raw?: Record<string, unknown>;
}

export interface EventDetails {
  event: MonitoringEvent;
  action_v1?: Action;
  action_v2_gnn?: Action;
}

export interface Summary {
  total_events: number;
  total_warnings: number;
  total_critical: number;
  routed_v1: number;
  routed_v2: number;
  domain_distribution: Record<string, number>;
  anomaly_distribution: Record<string, number>;
  severity_timeline: Array<{ timestamp: string; normal: number; warning: number; critical: number }>;
  top_anomaly_types: Array<{ name: string; count: number }>;
}

export interface PipelineStatus {
  last_message_ts?: string;
  bus_activity_last_2m: number;
  events_last_2m: number;
  actions_last_2m: number;
  status: 'live' | 'stale' | 'idle';
}
