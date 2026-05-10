import axios from 'axios';
import { Action, EventDetails, MonitoringEvent, PipelineStatus, Summary } from './types';

const defaultApiBaseUrl = `http://${window.location.hostname || '127.0.0.1'}:8000`;

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? defaultApiBaseUrl,
  timeout: 30000,
});

export async function fetchSummary() {
  const { data } = await api.get<Summary>('/api/summary');
  return data;
}

export async function fetchEvents(params: Record<string, string>) {
  const { data } = await api.get<MonitoringEvent[]>('/api/events', { params });
  return data;
}

export async function fetchEventDetails(eventId: string) {
  const { data } = await api.get<EventDetails>(`/api/events/${eventId}`);
  return data;
}

export async function fetchActions(params: Record<string, string>) {
  const { data } = await api.get<Action[]>('/api/actions', { params });
  return data;
}

export async function fetchActionComparison() {
  const { data } = await api.get<Array<{ event_id: string; v1?: Action; v2_gnn?: Action }>>('/api/actions/comparison');
  return data;
}

export async function fetchRawLogs() {
  const { data } = await api.get<Record<string, string[]>>('/api/logs/raw');
  return data;
}

export async function fetchPipelineStatus() {
  const { data } = await api.get<PipelineStatus>('/api/pipeline/status');
  return data;
}
