function csvCell(v) {
  const s = String(v ?? '');
  return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}

function fmtPct(pct, date) {
  if (pct == null) return '—';
  const p = (pct > 0 ? '+' : '') + pct.toFixed(2) + '%';
  return date ? `${p}(${date})` : p;
}

function toNum(v) {
  if (v == null || v === '') return null;
  const n = typeof v === 'number' ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

const PERIODS = [
  { label: 'T+1',  pct: 't1_pct',  date: 't1_date' },
  { label: 'T+3',  pct: 't3_pct',  date: 't3_date' },
  { label: 'T+7',  pct: 't7_pct',  date: 't7_date' },
  { label: 'T+15', pct: 't15_pct', date: 't15_date' },
  { label: 'T+30', pct: 't30_pct', date: 't30_date' },
];

// 行业涨幅排行：按行业聚合，取平均涨幅，从高到低排序（忽略无该周期数据的个股）
function buildIndustryRanking(rows, pctKey) {
  const groups = new Map();
  for (const r of rows || []) {
    const v = toNum(r[pctKey]);
    if (v == null) continue;
    const ind = (r.industry || '').trim() || '未分类';
    const g = groups.get(ind) || { sum: 0, count: 0 };
    g.sum += v;
    g.count += 1;
    groups.set(ind, g);
  }
  return [...groups.entries()]
    .map(([industry, g]) => ({ industry, avg: g.sum / g.count, count: g.count }))
    .sort((a, b) => b.avg - a.avg);
}

// 个股涨幅排行：按涨幅从高到低排序（忽略无该周期数据的个股）
function buildStockRanking(rows, pctKey) {
  return (rows || [])
    .map(r => ({
      code: r.stock_code,
      name: r.stock_name,
      industry: (r.industry || '').trim() || '未分类',
      pct: toNum(r[pctKey]),
    }))
    .filter(x => x.pct != null)
    .sort((a, b) => b.pct - a.pct);
}

export function downloadAllPicksCsv(rows) {
  const out = [];
  const push = (cells) => out.push(cells.map(csvCell).join(','));

  // 一、原始明细
  push(['批次', '策略', '日期', '代码', '名称', '行业', '主营', '选入价', 'T+1', 'T+3', 'T+7', 'T+15', 'T+30']);
  for (const r of rows || []) {
    push([
      r.pick_id,
      r.strategy_name,
      r.created_at,
      r.stock_code,
      r.stock_name,
      r.industry || '',
      (r.business_summary || '').replace(/[\r\n]+/g, ' '),
      r.t0_price != null ? r.t0_price.toFixed(2) : '',
      fmtPct(r.t1_pct, r.t1_date),
      fmtPct(r.t3_pct, r.t3_date),
      fmtPct(r.t7_pct, r.t7_date),
      fmtPct(r.t15_pct, r.t15_date),
      fmtPct(r.t30_pct, r.t30_date),
    ]);
  }

  // 二、行业涨幅排行（T+1 / T+3 / T+7 / T+15 / T+30 五张表）
  push([]);
  push(['========== 一、行业涨幅排行（按平均涨幅从高到低） ==========']);
  for (const p of PERIODS) {
    push([]);
    push([`—— ${p.label} 行业排行 ——`]);
    push(['行业', '平均涨幅', '股票数']);
    for (const g of buildIndustryRanking(rows, p.pct)) {
      push([g.industry, (g.avg > 0 ? '+' : '') + g.avg.toFixed(2) + '%', g.count]);
    }
  }

  // 三、个股涨幅排行（T+1 / T+3 / T+7 / T+15 / T+30 五张表）
  push([]);
  push(['========== 二、个股涨幅排行（按涨幅从高到低） ==========']);
  for (const p of PERIODS) {
    push([]);
    push([`—— ${p.label} 个股排行 ——`]);
    push(['代码', '名称', '行业', '涨幅']);
    for (const s of buildStockRanking(rows, p.pct)) {
      push([s.code, s.name, s.industry, (s.pct > 0 ? '+' : '') + s.pct.toFixed(2) + '%']);
    }
  }

  const csv = out.map(r => r.join(',')).join('\n');
  const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = '策略批次_报告分析.csv';
  a.click();
  URL.revokeObjectURL(url);
}
