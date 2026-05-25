import { useState, useEffect, useCallback } from 'react';
import { reportAPI } from '../api/client';

export function useReports({ refreshInterval = 30000, sort = 'performance', order = 'desc' } = {}) {
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchReports = useCallback(async () => {
    try {
      const data = await reportAPI.list(sort, order);
      setReports(data);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [sort, order]);

  useEffect(() => {
    setLoading(true);
    fetchReports();
    const interval = setInterval(fetchReports, refreshInterval);
    return () => clearInterval(interval);
  }, [fetchReports, refreshInterval]);

  return { reports, loading, error, refetch: fetchReports };
}
