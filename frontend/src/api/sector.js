import client from './client.js';

export async function listSectorPicks(status = null, extraParams = {}) {
  const params = { ...extraParams };
  if (status) params.status = status;
  const res = await client.get('/sector-picks', { params });
  return res.data;
}

export async function getSectorPick(id) {
  const res = await client.get(`/sector-picks/${id}`);
  return res.data;
}

export async function archiveSectorPick(id) {
  const res = await client.post(`/sector-picks/${id}/archive`);
  return res.data;
}

export async function deleteSectorPick(id) {
  const res = await client.delete(`/sector-picks/${id}`);
  return res.data;
}

export async function createSectorPick(payload) {
  const res = await client.post('/sector-picks', payload);
  return res.data;
}
