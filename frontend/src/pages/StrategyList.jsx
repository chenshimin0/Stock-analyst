import { useEffect, useState, useMemo } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { listStrategyPicks, deleteStrategyPick, deleteStockRow } from '../api/strategy.js';
import { listStrategies } from '../api/strategies.js';

const TABS = [
  { key: 'active', label: '进行中', statuses: ['in_progress', 'completed'] },
  { key: 'archived', label: '已归档', statuses: ['archived'] },
];

export default function StrategyList() {
  const [tab, setTab] = useState('active');
  const [picks, setPicks] = useState([]);
  const [strategies, setStrategies] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);
  const [params] = useSearchParams();
  const filterStrategyId = params.get('strategy_id') ? Number(params.get('strategy_id')) : null;

  // Filters
  const [selectedStrategy, setSelectedStrategy] = useState(filterStrategyId ? String(filterStrategyId) : '');
  const [selectedDate, setSelectedDate] = useState('');
  const [stockFilter, setStockFilter] = useState('');

  useEffect(() => {
    setLoading(true);
    setErr(null);
    const statuses = TABS.find(t => t.key === tab).statuses;
    // Fetch all picks (no strategy filter) so we can derive dates client-side
    const pickPromises = statuses.map(s => listStrategyPicks(s).catch(() => []));
    Promise.all([...pickPromises, listStrategies().catch(() => [])])
      .then((results) => {
        const strats = results.pop();
        setPicks(results.flat());
        setStrategies(strats);
      })
      .catch(e => setErr(String(e)))
      .finally(() => setLoading(false));
  }, [tab]);

  // Set initial strategy from URL param
  useEffect(() => {
    if (filterStrategyId) setSelectedStrategy(String(filterStrategyId));
  }, [filterStrategyId]);

  // --- Derived data ---
  // All unique dates from picks (sorted newest first)
  const allDates = useMemo(() => {
    return [...new Set(picks.map(p => {
      return new Date(p.created_at).toISOString().split('T')[0];
    }))].sort().reverse();
  }, [picks]);

  // Dates that have data for the currently selected strategy
  const strategyDates = useMemo(() => {
    if (!selectedStrategy) return new Set(allDates);
    return new Set(picks
      .filter(p => p.strategy_id === Number(selectedStrategy))
      .map(p => new Date(p.created_at).toISOString().split('T')[0])
    );
  }, [picks, selectedStrategy, allDates]);

  // Filtered picks
  const filteredPicks = useMemo(() => {
    return picks.filter(p => {
      if (selectedStrategy && p.strategy_id !== Number(selectedStrategy)) return false;
      if (selectedDate) {
        const d = new Date(p.created_at).toISOString().split('T')[0];
        if (d !== selectedDate) return false;
      }
      if (stockFilter.trim()) {
        const q = stockFilter.trim().toLowerCase();
        const stocks = p.stocks_preview || [];
        return stocks.some(s =>
          s.stock_code.toLowerCase().includes(q) ||
          s.stock_name.toLowerCase().includes(q)
        );
      }
      return true;
    });
  }, [picks, selectedStrategy, selectedDate, stockFilter]);

  const strategyName = (id, name) => name || strategies.find(s => s.id === id)?.name || `#${id}`;

  return (
    <div style={{ padding: 24 }}>
      <h2 style={{ marginBottom: 16 }}>🎯 策略追踪</h2>

      {/* Filters row */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, alignItems: 'center', flexWrap: 'wrap' }}>
        {/* Tab buttons */}
        {TABS.map(t => (
          <button
            key={t.key}
            onClick={() => { setTab(t.key); setSelectedDate(''); }}
            style={{
              padding: '6px 14px',
              border: '1px solid #ccc',
              background: tab === t.key ? '#1565c0' : '#fff',
              color: tab === t.key ? '#fff' : '#333',
              borderRadius: 4,
              cursor: 'pointer',
            }}
          >
            {t.label}
          </button>
        ))}

        <div style={{ width: 1, height: 24, background: '#ddd' }} />

        {/* Strategy filter */}
        <select
          value={selectedStrategy}
          onChange={e => { setSelectedStrategy(e.target.value); setSelectedDate(''); }}
          style={{
            padding: '6px 10px', border: '1px solid #ccc', borderRadius: 4,
            fontSize: 13, background: '#fff', minWidth: 140,
          }}
        >
          <option value="">全部策略</option>
          {strategies.map(s => (
            <option key={s.id} value={String(s.id)}>{s.name}</option>
          ))}
        </select>

        {/* Date filter */}
        <select
          value={selectedDate}
          onChange={e => setSelectedDate(e.target.value)}
          style={{
            padding: '6px 10px', border: '1px solid #ccc', borderRadius: 4,
            fontSize: 13, background: '#fff', minWidth: 130,
          }}
        >
          <option value="">全部日期</option>
          {allDates.map(d => {
            const hasData = strategyDates.has(d);
            return (
              <option
                key={d}
                value={d}
                disabled={!hasData}
                style={{
                  color: hasData ? '#000' : '#ccc',
                  fontWeight: hasData ? 600 : 400,
                  background: hasData ? '#e8f5e9' : undefined,
                }}
              >
                {d}{hasData ? ' ✓' : ' (无数据)'}
              </option>
            );
          })}
        </select>

        {/* Result count */}
        <span style={{ fontSize: 12, color: '#888', marginLeft: 4 }}>
          {filteredPicks.length} / {picks.length} 个批次
        </span>

        <div style={{ width: 1, height: 24, background: '#ddd' }} />

        {/* Stock filter */}
        <input
          type="text"
          placeholder="按股票代码/名称筛选..."
          value={stockFilter}
          onChange={e => setStockFilter(e.target.value)}
          style={{
            padding: '6px 10px', border: '1px solid #ccc', borderRadius: 4,
            fontSize: 13, width: 180,
          }}
        />
        {stockFilter && (
          <button onClick={() => setStockFilter('')} style={{
            padding: '4px 8px', background: '#fff', color: '#666',
            border: '1px solid #ccc', borderRadius: 4, cursor: 'pointer', fontSize: 12,
          }}>
            清除
          </button>
        )}
      </div>

      {loading && <div>加载中…</div>}
      {err && <div style={{ color: 'red' }}>{err}</div>}

      {!loading && filteredPicks.length === 0 && (
        <div style={{ color: '#888', padding: 24, textAlign: 'center' }}>
          {selectedStrategy || selectedDate
            ? '没有匹配的批次。尝试清除筛选条件。'
            : tab === 'active'
              ? '还没有策略批次。每天 14:30 自动跑 iwencai 选股，结果会出现在这里。'
              : '没有归档批次。'}
        </div>
      )}

      {!loading && filteredPicks.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {filteredPicks.map(p => (
            <PickCard
              key={p.id}
              pick={p}
              stockFilter={stockFilter}
              strategyName={strategyName}
              onDeleted={(id) => setPicks(prev => prev.filter(x => x.id !== id))}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function PickCard({ pick, stockFilter, strategyName, onDeleted }) {
  const preview = pick.stocks_preview || [];
  const hidden = pick.hit_count - preview.length;

  const q = (stockFilter || '').trim().toLowerCase();
  const isMatch = (s) => q && (s.stock_code.toLowerCase().includes(q) || s.stock_name.toLowerCase().includes(q));

  const handleDeleteStock = async (stockId, stockName) => {
    if (!confirm(`确认从批次 #${pick.id} 中删除 ${stockName}？`)) return;
    try {
      await deleteStockRow(stockId);
      // Refresh by fetching again
      window.location.reload();
    } catch (e) {
      alert('删除失败：' + e.message);
    }
  };

  const handleDelete = async () => {
    if (!confirm(`确认永久删除批次 #${pick.id}？\n该批次 ${pick.hit_count} 只股票的 T+N 追踪数据将全部丢失。`)) return;
    try {
      await deleteStrategyPick(pick.id);
      onDeleted(pick.id);
    } catch (e) {
      alert('删除失败：' + e.message);
    }
  };

  return (
    <div style={{
      background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8,
      padding: 16, boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
      position: 'relative',
    }}>
      {/* header row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 10, flexWrap: 'wrap' }}>
        <Link to={`/strategy/${pick.id}`} style={{ fontSize: 16, fontWeight: 700, color: '#1565c0' }}>
          #{pick.id}
        </Link>
        <span style={{ fontSize: 14, color: '#e5e7eb' }}>{strategyName(pick.strategy_id, pick.strategy_name)}</span>
        <StatusBadge status={pick.status} />
        <span style={{ fontSize: 12, color: '#9ca3af' }}>
          {new Date(pick.created_at).toLocaleString()}
        </span>
        <span style={{ fontSize: 12, color: '#9ca3af' }}>
          命中 <b style={{ color: '#60a5fa' }}>{pick.hit_count}</b> 只
        </span>
        <div style={{ flex: 1 }} />
        <AvgCells pick={pick} />
        <button
          onClick={handleDelete}
          title="永久删除该批次"
          style={{
            padding: '4px 10px', background: '#fff',
            border: '1px solid #d32f2f', color: '#d32f2f',
            borderRadius: 4, cursor: 'pointer', fontSize: 12, fontWeight: 600,
          }}
        >
          🗑️ 删除
        </button>
      </div>

      {/* query text */}
      {pick.query_text && (
        <div style={{
          fontFamily: 'monospace', fontSize: 11, color: '#9ca3af',
          background: '#1a2236', padding: '6px 10px', borderRadius: 4,
          marginBottom: 10, wordBreak: 'break-all', lineHeight: 1.5,
          border: '1px solid #1e293b',
        }}>
          {pick.query_text}
        </div>
      )}

      {/* stock preview table */}
      {preview.length > 0 ? (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: '#1e293b' }}>
              <th style={{...th, color: '#e5e7eb', borderRadius: '6px 0 0 0'}}>代码</th>
              <th style={{...th, color: '#e5e7eb'}}>名称</th>
              <th style={{...th, color: '#e5e7eb'}}>行业</th>
              <th style={{...th, color: '#e5e7eb'}}>选入价</th>
              <th style={{...th, color: '#e5e7eb'}}>T+1</th>
              <th style={{...th, color: '#e5e7eb'}}>T+3</th>
              <th style={{...th, color: '#e5e7eb'}}>T+7</th>
              <th style={{...th, color: '#e5e7eb'}}>T+15</th>
              <th style={{...th, color: '#e5e7eb', borderRadius: '0 6px 0 0'}}>T+30</th>
              <th style={{...th, color: '#e5e7eb', width: 30}}></th>
            </tr>
          </thead>
          <tbody>
            {preview.map((s, i) => {
              const matched = isMatch(s);
              return (
              <tr key={s.id} style={{
                borderBottom: '1px solid #1e293b',
                background: matched ? 'rgba(234,179,8,0.15)' : i % 2 === 0 ? '#0f172a' : '#1a2236',
                transition: 'background 0.15s',
              }}
              onMouseEnter={e => e.currentTarget.style.background = matched ? 'rgba(234,179,8,0.25)' : '#1e3a5f'}
              onMouseLeave={e => e.currentTarget.style.background = matched ? 'rgba(234,179,8,0.15)' : i % 2 === 0 ? '#0f172a' : '#1a2236'}
              >
                <td style={td}><a href={`https://www.iwencai.com/screener/result?w=${encodeURIComponent(s.stock_name)}`} target="_blank" rel="noopener" style={{ textDecoration: 'none' }} title={`在 i 问财查看 ${s.stock_name}`}><code style={{ fontSize: 12, color: '#93c5fd' }}>{s.stock_code}</code></a></td>
                <td style={{ ...td, fontWeight: 600, color: '#f0f6fc' }}>{s.stock_name}</td>
                <td style={td}><span style={{ color: s.industry ? '#9ca3af' : '#4b5563', fontSize: 12 }}>{s.industry || '—'}</span></td>
                <td style={td}>{s.t0_price != null ? s.t0_price.toFixed(2) : '—'}</td>
                <td style={td}><Pct value={s.t1_pct} /></td>
                <td style={td}><Pct value={s.t3_pct} /></td>
                <td style={td}><Pct value={s.t7_pct} /></td>
                <td style={td}><Pct value={s.t15_pct} /></td>
                <td style={td}><Pct value={s.t30_pct} /></td>
                <td style={{...td, padding: '2px'}}>
                  <button
                    onClick={(e) => { e.stopPropagation(); handleDeleteStock(s.id, s.stock_name); }}
                    title="从批次中删除"
                    style={{ background: 'rgba(239,68,68,0.12)', color: '#ef4444', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 4, cursor: 'pointer', fontSize: 11, padding: '2px 5px' }}
                  >✕</button>
                </td>
              </tr>
              );
            })}
          </tbody>
        </table>
      ) : (
        <div style={{ color: '#6b7280', fontSize: 12, padding: '6px 0' }}>该批次没有股票记录</div>
      )}

      {hidden > 0 && (
        <div style={{ marginTop: 6, fontSize: 12, color: '#60a5fa' }}>
          还有 {hidden} 只未显示 — <Link to={`/strategy/${pick.id}`}>查看全部</Link>
        </div>
      )}
    </div>
  );
}

function AvgCells({ pick }) {
  const cells = [
    { label: 'T+1', v: pick.avg_t1_pct },
    { label: 'T+3', v: pick.avg_t3_pct },
    { label: 'T+7', v: pick.avg_t7_pct },
    { label: 'T+15', v: pick.avg_t15_pct },
    { label: 'T+30', v: pick.avg_t30_pct },
  ];
  return (
    <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
      <span style={{ fontSize: 11, color: '#888' }}>均值</span>
      {cells.map(c => (
        <div key={c.label} style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 10, color: '#999' }}>{c.label}</div>
          <Pct value={c.v} small />
        </div>
      ))}
    </div>
  );
}

function StatusBadge({ status }) {
  const map = {
    in_progress: { label: '进行中', bg: '#e3f2fd', color: '#1565c0' },
    completed: { label: '已完成', bg: '#e8f5e9', color: '#2e7d32' },
    archived: { label: '已归档', bg: '#f5f5f5', color: '#666' },
  };
  const cfg = map[status] || { label: status, bg: '#eee', color: '#333' };
  return (
    <span style={{
      padding: '2px 8px', background: cfg.bg, color: cfg.color,
      borderRadius: 4, fontSize: 12,
    }}>
      {cfg.label}
    </span>
  );
}

function Pct({ value, small }) {
  if (value == null) return <span style={{ color: '#6b7280', fontSize: small ? 12 : 13 }}>—</span>;
  const isPos = value > 0;
  const isNeg = value < 0;
  const color = isPos ? '#ef4444' : isNeg ? '#22c55e' : '#d1d5db';
  const bg = isPos ? 'rgba(239,68,68,0.12)' : isNeg ? 'rgba(34,197,94,0.12)' : 'transparent';
  return (
    <span style={{
      color, fontWeight: 700, fontSize: small ? 12 : 14,
      background: bg, padding: '2px 8px', borderRadius: 4,
    }}>
      {value > 0 ? '+' : ''}{value.toFixed(2)}%
    </span>
  );
}

const th = { padding: '6px 10px', textAlign: 'left', fontSize: 12, fontWeight: 600, color: '#e5e7eb' };
const td = { padding: '6px 10px', fontSize: 13, color: '#f1f5f9' };
