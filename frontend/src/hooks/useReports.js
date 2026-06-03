import { useState, useEffect, useCallback } from 'react';
import { reportAPI } from '../api/client';

export function useReports({ refreshInterval = 30000, sort = 'performance', order = 'desc', page = 1, pageSize = 20 } = {}) {
  const [reports, setReports] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchReports = useCallback(async () => {
    try {
      const data = await reportAPI.list(sort, order, page, pageSize);
      setReports(data.items || []);
      setTotal(data.total || 0);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [sort, order, page, pageSize]);

  useEffect(() => {
    setLoading(true);
    fetchReports();
    const interval = setInterval(fetchReports, refreshInterval);
    return () => clearInterval(interval);
  }, [fetchReports, refreshInterval]);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return { reports, total, totalPages, loading, error, refetch: fetchReports };
}
