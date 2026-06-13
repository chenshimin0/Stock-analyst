import client from './client.js';

export async function listStrategies() {
  const res = await client.get('/strategies');
  return res.data;
}

export async function getStrategy(id) {
  const res = await client.get(`/strategies/${id}`);
  return res.data;
}

export async function createStrategy(payload) {
  const res = await client.post('/strategies', payload);
  return res.data;
}

export async function updateStrategy(id, payload) {
  const res = await client.put(`/strategies/${id}`, payload);
  return res.data;
}

export async function deleteStrategy(id) {
  const res = await client.delete(`/strategies/${id}`);
  return res.data;
}

export async function toggleStrategy(id) {
  const res = await client.post(`/strategies/${id}/toggle`);
  return res.data;
}

export async function runStrategyNow(id) {
  const res = await client.post(`/strategies/${id}/run`);
  return res.data;
}
