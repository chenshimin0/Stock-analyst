import { useState, useEffect, useCallback } from 'react';
import { reportAPI } from '../api/client';

export function useWinRate(reportId) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetch = useCallback(async () => {
    if (!reportId) return;
    try {
      const result = await reportAPI.winrate(reportId);
      setData(result);
    } catch (err) {
      // silent fail
    } finally {
      setLoading(false);
    }
  }, [reportId]);

  useEffect(() => { fetch(); }, [fetch]);

  return { data, loading, refetch: fetch };
}

export function useAggregateWinRate() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetch = useCallback(async () => {
    try {
      const result = await reportAPI.aggWinrate();
      setData(result);
    } catch (err) {
      // silent fail
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetch(); }, [fetch]);

  return { data, loading, refetch: fetch };
}
