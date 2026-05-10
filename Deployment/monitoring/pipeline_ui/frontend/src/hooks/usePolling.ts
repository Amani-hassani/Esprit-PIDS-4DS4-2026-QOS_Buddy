import { useEffect } from 'react';

export function usePolling(callback: () => void, intervalMs = 2000) {
  useEffect(() => {
    callback();
    const id = setInterval(callback, intervalMs);
    return () => clearInterval(id);
  }, [callback, intervalMs]);
}
