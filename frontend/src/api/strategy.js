import client from './client.js';

export async function listStrategyPicks(status = null) {
  const params = status ? { status } : {};
  const res = await client.get('/strategy-picks', { params });
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
