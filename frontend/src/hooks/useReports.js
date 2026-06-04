import { useState, useEffect, useCallback, useRef } from 'react';
import { reportAPI } from '../api/client';

export function useReports({ refreshInterval = 30000, sort = 'performance', order = 'desc', page = 1, pageSize = 20, search = '' } = {}) {
  const [reports, setReports] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const mounted = useRef(false);

  const fetchReports = useCallback(async (showLoading = false) => {
    if (showLoading) setLoading(true);
    try {
      const data = await reportAPI.list(sort, order, page, pageSize, search);
      setReports(data.items || []);
      setTotal(data.total || 0);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [sort, order, page, pageSize, search]);

  useEffect(() => {
    if (!mounted.current) {
      // Initial mount: show loading spinner
      fetchReports(true);
      mounted.current = true;
    } else {
      // Params changed (sort/page/search): update silently, no loading flash
      fetchReports(false);
    }

    const interval = setInterval(() => fetchReports(false), refreshInterval);
    return () => clearInterval(interval);
  }, [fetchReports, refreshInterval]);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return { reports, total, totalPages, loading, error, refetch: () => fetchReports(false) };
}
