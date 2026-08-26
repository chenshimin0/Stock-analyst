import client from './client.js';

export async function listStrategyPicks(params = {}) {
  const res = await client.get('/strategy-picks', { params });
  return res.data;
}

export async function exportStrategyPicks(params = {}) {
  const res = await client.get('/strategy-picks/export', { params });
  return res.data;
}

export async function getStrategyPick(id) {
  const res = await client.get(`/strategy-picks/${id}`);
  return res.data;
}

export async function archiveStrategyPick(id) {
  const res = await client.post(`/strategy-picks/${id}/archive`);
  return res.data;
}

export async function deleteStrategyPick(id) {
  const res = await client.delete(`/strategy-picks/${id}`);
  return res.data;
}

export async function deleteStockRow(stockId) {
  const res = await client.delete(`/strategy-picks/stock/${stockId}`);
  return res.data;
}
