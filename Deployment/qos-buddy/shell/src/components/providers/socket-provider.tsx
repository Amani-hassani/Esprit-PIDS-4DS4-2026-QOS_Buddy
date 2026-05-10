"use client";

import { useEffect } from "react";
import { useAuth } from "./auth-provider";
import { disconnectSocket, getSocket, Streams } from "@/lib/socket";
import { useLive } from "@/lib/store";
import type {
  AlertEvent,
  AuditEvent,
  DiagnosisEvent,
  ExecutedActionEvent,
  InsightEvent,
  JiraTicket,
  MetricEvent,
  MePayload,
  ProposedActionEvent,
} from "@/lib/types";

/**
 * Connects to the gateway with the Keycloak access token, subscribes to every
 * stream the role is allowed, and pushes events into the Zustand store.
 *
 * No mock data path. If the socket can't connect, components show empty
 * states with the connection status.
 */
export function SocketProvider({ children }: { children: React.ReactNode }) {
  const { authenticated, token, role } = useAuth();
  const setConnected = useLive((s) => s.setConnected);
  const pushMetric = useLive((s) => s.pushMetric);
  const pushAlert = useLive((s) => s.pushAlert);
  const upsertDiagnosis = useLive((s) => s.upsertDiagnosis);
  const upsertInsight = useLive((s) => s.upsertInsight);
  const pushProposed = useLive((s) => s.pushProposed);
  const pushExecuted = useLive((s) => s.pushExecuted);
  const pushTicket = useLive((s) => s.pushTicket);
  const pushAudit = useLive((s) => s.pushAudit);

  const { demoMode } = useAuth();
  const effectiveToken = demoMode ? `demo:${role}` : token;

  useEffect(() => {
    if (!authenticated || !effectiveToken) return;
    const socket = getSocket(effectiveToken);

    const routeEvent = (stream: string, payload: unknown) => {
      if (!payload || typeof payload !== "object") return;
      if (stream === Streams.METRICS) pushMetric(payload as MetricEvent);
      else if (stream === Streams.ALERTS) pushAlert(payload as AlertEvent);
      else if (stream === Streams.DIAGNOSIS) upsertDiagnosis(payload as DiagnosisEvent);
      else if (stream === Streams.INSIGHT) upsertInsight(payload as InsightEvent);
      else if (stream === Streams.ACTION_PROPOSED) pushProposed(payload as ProposedActionEvent);
      else if (stream === Streams.ACTION_EXECUTED) pushExecuted(payload as ExecutedActionEvent);
      else if (stream === Streams.JIRA_OUTBOX || stream === Streams.JIRA_TICKETS) pushTicket(payload as JiraTicket);
      else if (stream === Streams.AUDIT) pushAudit(payload as AuditEvent);
    };

    const hydrateSnapshot = async (stream: string) => {
      try {
        const res = await fetch(
          `${process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:8080"}/api/snapshot/${encodeURIComponent(stream)}?count=200`,
          { headers: { authorization: `Bearer ${effectiveToken}` } },
        );
        if (!res.ok) return;
        const data = (await res.json()) as { items?: unknown[] };
        for (const item of data.items ?? []) routeEvent(stream, item);
      } catch {
        // Live socket events still populate the page if a snapshot is denied or delayed.
      }
    };

    const onConnect = () => setConnected(true);
    const onDisconnect = () => setConnected(false);
    const onReady = (payload: MePayload) => {
      for (const stream of payload.allowed_streams) {
        socket.emit("subscribe", { stream });
        void hydrateSnapshot(stream);
      }
    };

    socket.on("connect", onConnect);
    socket.on("disconnect", onDisconnect);
    socket.on("ready", onReady);

    socket.on(Streams.METRICS, (m: MetricEvent) => pushMetric(m));
    socket.on(Streams.ALERTS, (a: AlertEvent) => pushAlert(a));
    socket.on(Streams.DIAGNOSIS, (d: DiagnosisEvent) => upsertDiagnosis(d));
    socket.on(Streams.INSIGHT, (i: InsightEvent) => upsertInsight(i));
    socket.on(Streams.ACTION_PROPOSED, (p: ProposedActionEvent) => pushProposed(p));
    socket.on(Streams.ACTION_EXECUTED, (e: ExecutedActionEvent) => pushExecuted(e));
    socket.on(Streams.JIRA_OUTBOX, (t: JiraTicket) => pushTicket(t));
    socket.on("jira:ticket", (t: JiraTicket) => pushTicket(t));
    socket.on(Streams.AUDIT, (e: AuditEvent) => pushAudit(e));

    return () => {
      socket.off("connect", onConnect);
      socket.off("disconnect", onDisconnect);
      socket.off("ready", onReady);
      socket.off(Streams.METRICS);
      socket.off(Streams.ALERTS);
      socket.off(Streams.DIAGNOSIS);
      socket.off(Streams.INSIGHT);
      socket.off(Streams.ACTION_PROPOSED);
      socket.off(Streams.ACTION_EXECUTED);
      socket.off(Streams.JIRA_OUTBOX);
      socket.off("jira:ticket");
      socket.off(Streams.AUDIT);
    };
  }, [
    authenticated,
    effectiveToken,
    role,
    setConnected,
    pushMetric,
    pushAlert,
    upsertDiagnosis,
    upsertInsight,
    pushProposed,
    pushExecuted,
    pushTicket,
    pushAudit,
  ]);

  useEffect(() => {
    return () => {
      disconnectSocket();
    };
  }, []);

  return <>{children}</>;
}
