import { useState, useEffect, useCallback } from 'react';
import { stockAPI } from '../api/client';

export function useStockPrice(stockCode, { refreshInterval = 30000 } = {}) {
  const [priceData, setPriceData] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchPrice = useCallback(async () => {
    if (!stockCode) return;
    try {
      const data = await stockAPI.price(stockCode);
      setPriceData(data);
    } catch (err) {
      // silent fail
    } finally {
      setLoading(false);
    }
  }, [stockCode]);

  useEffect(() => {
    fetchPrice();
    const interval = setInterval(fetchPrice, refreshInterval);
    return () => clearInterval(interval);
  }, [fetchPrice, refreshInterval]);

  return { priceData, loading, refetch: fetchPrice };
}
