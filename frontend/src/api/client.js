import axios from 'axios';

const api = axios.create({ baseURL: '/api' });

export const reportAPI = {
  list:      (sort='performance', order='desc', page=1, page_size=20, search='') => api.get('/reports', { params: { sort, order, page, page_size, search } }).then(r => r.data),
  get:       (id, fmt='json')=> api.get(`/reports/${id}`, { params: { format: fmt } }).then(r => r.data),
  create:    (data)          => api.post('/reports', data).then(r => r.data),
  winrate:   (id)            => api.get(`/reports/${id}/winrate`).then(r => r.data),
  winrateAll:()              => api.get('/reports/winrate/all').then(r => r.data),
  aggWinrate:()              => api.get('/reports/winrate/aggregate').then(r => r.data),
  refreshPrices:()           => api.post('/reports/refresh-prices').then(r => r.data),
};

export const stockAPI = {
  price:    (code)           => api.get(`/stocks/${code}/price`).then(r => r.data),
  prices:   (codes)          => api.post('/stocks/prices', codes).then(r => r.data),
};
