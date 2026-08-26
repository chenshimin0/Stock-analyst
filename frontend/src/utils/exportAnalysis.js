import * as XLSX from 'xlsx';

const PERIODS = [
  { label: 'T+1',  pct: 't1_pct' },
  { label: 'T+3',  pct: 't3_pct' },
  { label: 'T+7',  pct: 't7_pct' },
  { label: 'T+15', pct: 't15_pct' },
  { label: 'T+30', pct: 't30_pct' },
];
const PERIOD_KEYS = PERIODS.map(p => p.pct);
const PERIOD_LABELS = PERIODS.map(p => p.label);

function toNum(v) {
  if (v == null || v === '') return null;
  const n = typeof v === 'number' ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

function fmtPct(pct) {
  if (pct == null) return '—';
  return (pct > 0 ? '+' : '') + pct.toFixed(2) + '%';
}

function avg(nums) {
  const vals = nums.filter(v => v != null);
  if (!vals.length) return null;
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}

// ============ Sheet 1：原始明细 ============
function buildDetailSheet(rows) {
  // 按日期倒序（最新在前），同日期按批次倒序
  const sorted = [...(rows || [])].sort((a, b) => {
    const da = a.created_at || '';
    const db = b.created_at || '';
    if (da !== db) return db.localeCompare(da);
    return (b.pick_id ?? 0) - (a.pick_id ?? 0);
  });
  const aoa = [['批次', '策略', '日期', '代码', '名称', '行业', '主营', '选入价', ...PERIOD_LABELS]];
  for (const r of sorted) {
    aoa.push([
      r.pick_id,
      r.strategy_name,
      r.created_at,
      r.stock_code,
      r.stock_name,
      r.industry || '',
      (r.business_summary || '').replace(/[\r\n]+/g, ' '),
      r.t0_price != null ? r.t0_price : '',
      fmtPct(toNum(r.t1_pct)),
      fmtPct(toNum(r.t3_pct)),
      fmtPct(toNum(r.t7_pct)),
      fmtPct(toNum(r.t15_pct)),
      fmtPct(toNum(r.t30_pct)),
    ]);
  }
  return aoa;
}

// ============ Sheet 2：策略盈亏率 ============
function buildStrategySheet(rows) {
  const byStrategy = new Map();
  for (const r of rows || []) {
    const name = r.strategy_name || '(未知)';
    if (!byStrategy.has(name)) {
      byStrategy.set(name, { name, count: 0, pcts: PERIOD_KEYS.map(() => []) });
    }
    const g = byStrategy.get(name);
    g.count += 1;
    PERIOD_KEYS.forEach((k, i) => {
      const v = toNum(r[k]);
      if (v != null) g.pcts[i].push(v);
    });
  }
  const aoa = [['策略', ...PERIOD_LABELS, '样本数']];
  const list = [...byStrategy.values()].sort((a, b) => a.name.localeCompare(b.name, 'zh'));
  for (const g of list) {
    aoa.push([g.name, ...g.pcts.map(a => fmtPct(avg(a))), g.count]);
  }
  return aoa;
}

// ============ Sheet 3：个股盈亏 + 最佳离场 ============
function buildStockSheet(rows) {
  const byStock = new Map();
  for (const r of rows || []) {
    const code = r.stock_code;
    if (!byStock.has(code)) {
      byStock.set(code, { code, name: r.stock_name, industry: r.industry || '', pcts: PERIOD_KEYS.map(() => []) });
    }
    const g = byStock.get(code);
    if (!g.name) g.name = r.stock_name;
    if (!g.industry) g.industry = r.industry || '';
    PERIOD_KEYS.forEach((k, i) => {
      const v = toNum(r[k]);
      if (v != null) g.pcts[i].push(v);
    });
  }
  const aoa = [['代码', '名称', '行业', ...PERIOD_LABELS, '最佳离场']];
  const list = [...byStock.values()].sort((a, b) => a.code.localeCompare(b.code));
  for (const g of list) {
    const avgs = g.pcts.map(a => avg(a));
    let bestIdx = -1, bestVal = -Infinity;
    avgs.forEach((v, i) => {
      if (v != null && v > bestVal) { bestVal = v; bestIdx = i; }
    });
    const bestExit = bestIdx >= 0 ? PERIOD_LABELS[bestIdx] : '—';
    aoa.push([g.code, g.name, g.industry, ...avgs.map(fmtPct), bestExit]);
  }
  return aoa;
}

// ============ Sheet 4：每周板块涨幅 ============
function weekKey(dateStr) {
  if (!dateStr) return '(无日期)';
  const d = new Date(dateStr + 'T00:00:00');
  if (Number.isNaN(d.getTime())) return dateStr;
  const day = (d.getDay() + 6) % 7; // 0 = Monday
  d.setDate(d.getDate() - day);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${dd}`;
}

function buildWeeklySectorSheet(rows) {
  const groups = new Map(); // key: `${week}|${sector}`
  for (const r of rows || []) {
    const week = weekKey(r.created_at);
    const sector = (r.industry || '').trim() || '未分类';
    const key = week + '|' + sector;
    if (!groups.has(key)) {
      groups.set(key, { week, sector, pcts: PERIOD_KEYS.map(() => []) });
    }
    const g = groups.get(key);
    PERIOD_KEYS.forEach((k, i) => {
      const v = toNum(r[k]);
      if (v != null) g.pcts[i].push(v);
    });
  }

  const items = [...groups.values()].map(g => {
    const avgs = g.pcts.map(a => avg(a));
    return { ...g, avgs, overall: avg(avgs) };
  });
  items.sort((a, b) =>
    a.week === b.week
      ? (b.overall ?? -Infinity) - (a.overall ?? -Infinity)
      : b.week.localeCompare(a.week), // 周倒序：最新一周在前
  );

  const aoa = [['周', '板块', ...PERIOD_LABELS, '平均', '本周最高']];
  let prevWeek = null;
  for (const it of items) {
    const isTop = it.week !== prevWeek && it.overall != null;
    aoa.push([
      it.week, it.sector,
      ...it.avgs.map(fmtPct),
      fmtPct(it.overall),
      isTop ? '★ 最高' : '',
    ]);
    prevWeek = it.week;
  }
  return aoa;
}

// ============ 列宽（中文按 2 宽度计） ============
function setColWidths(ws, aoa, maxW = 42) {
  const cols = aoa[0] ? aoa[0].length : 0;
  const widths = [];
  for (let c = 0; c < cols; c++) {
    let w = 0;
    for (const row of aoa) {
      const cell = row[c];
      const s = cell == null ? '' : String(cell);
      const len = [...s].reduce((n, ch) => n + (/[⺀-￿]/.test(ch) ? 2 : 1), 0);
      if (len > w) w = len;
    }
    widths.push({ wch: Math.min(Math.max(w + 2, 6), maxW) });
  }
  ws['!cols'] = widths;
}

export function buildAnalysisWorkbook(rows) {
  const wb = XLSX.utils.book_new();

  const detail = buildDetailSheet(rows);
  const wsDetail = XLSX.utils.aoa_to_sheet(detail);
  setColWidths(wsDetail, detail);
  XLSX.utils.book_append_sheet(wb, wsDetail, '原始明细');

  const strategy = buildStrategySheet(rows);
  const wsStrategy = XLSX.utils.aoa_to_sheet(strategy);
  setColWidths(wsStrategy, strategy);
  XLSX.utils.book_append_sheet(wb, wsStrategy, '策略盈亏率');

  const stock = buildStockSheet(rows);
  const wsStock = XLSX.utils.aoa_to_sheet(stock);
  setColWidths(wsStock, stock);
  XLSX.utils.book_append_sheet(wb, wsStock, '个股盈亏与最佳离场');

  const weekly = buildWeeklySectorSheet(rows);
  const wsWeekly = XLSX.utils.aoa_to_sheet(weekly);
  setColWidths(wsWeekly, weekly);
  XLSX.utils.book_append_sheet(wb, wsWeekly, '每周板块涨幅');

  return wb;
}

export function downloadAnalysisXlsx(rows) {
  const wb = buildAnalysisWorkbook(rows);
  XLSX.writeFile(wb, '策略分析报告.xlsx');
}
