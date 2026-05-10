import { useCallback, useState } from 'react';
import { Route, Routes } from 'react-router-dom';
import { fetchPipelineStatus, fetchSummary } from './api';
import { Layout } from './components/Layout';
import { usePolling } from './hooks/usePolling';
import { ActionsPage } from './pages/ActionsPage';
import { DashboardPage } from './pages/DashboardPage';
import { EventsPage } from './pages/EventsPage';
import { LogsPage } from './pages/LogsPage';
import { PipelineStatus, Summary } from './types';

export default function App() {
  const [summary, setSummary] = useState<Summary>();
  const [status, setStatus] = useState<PipelineStatus>();
  const [apiConnected, setApiConnected] = useState(false);

  const loadHeaderData = useCallback(async () => {
    try {
      const [summaryData, statusData] = await Promise.all([fetchSummary(), fetchPipelineStatus()]);
      setSummary(summaryData);
      setStatus(statusData);
      setApiConnected(true);
    } catch {
      setApiConnected(false);
    }
  }, []);

  usePolling(loadHeaderData, 2000);

  return (
    <Routes>
      <Route element={<Layout status={status} apiConnected={apiConnected} />}>
        <Route path="/" element={<DashboardPage summary={summary} status={status} />} />
        <Route path="/events" element={<EventsPage />} />
        <Route path="/actions" element={<ActionsPage />} />
        <Route path="/logs" element={<LogsPage />} />
      </Route>
    </Routes>
  );
}
