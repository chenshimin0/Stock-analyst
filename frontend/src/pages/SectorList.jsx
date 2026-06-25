import React, { useEffect, useState, useCallback } from 'react';
import { listSectorPicks, getSectorPick, deleteSectorPick } from '../api/sector.js';

const TABS = [
  { key: 'active', label: '进行中', statuses: ['in_progress', 'completed'] },
  { key: 'archived', label: '已归档', statuses: ['archived'] },
];

export default function SectorList() {
  const [tab, setTab] = useState('active');
  const [picks, setPicks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);

  // Filters
  const [searchSector, setSearchSector] = useState('');
  const [searchStock, setSearchStock] = useState('');

  // Expand/collapse detail (multiple allowed)
  const [expandedIds, setExpandedIds] = useState(new Set());
  const [detailCache, setDetailCache] = useState({});  // id -> { loading, data, error }

  const toggleExpand = useCallback(async (id) => {
    const next = new Set(expandedIds);
    if (next.has(id)) {
      next.delete(id);
      setExpandedIds(next);
      return;
    }
    next.add(id);
    setExpandedIds(next);
    if (!detailCache[id]) {
      setDetailCache(prev => ({ ...prev, [id]: { loading: true, data: null, error: null } }));
      try {
        const data = await getSectorPick(id);
        setDetailCache(prev => ({ ...prev, [id]: { loading: false, data, error: null } }));
      } catch (e) {
        setDetailCache(prev => ({ ...prev, [id]: { loading: false, data: null, error: e.message } }));
      }
    }
  }, [expandedIds, detailCache]);

  const handleDelete = async (id, name) => {
    if (!confirm(`确认删除板块 "${name}" 及其追踪数据？`)) return;
    try {
      await deleteSectorPick(id);
      setPicks(prev => prev.filter(p => p.id !== id));
      const next = new Set(expandedIds);
      next.delete(id);
      setExpandedIds(next);
    } catch (e) {
      alert(`删除失败：${e.message}`);
    }
  };

  const load = () => {
    setLoading(true);
    setErr(null);
    const statuses = TABS.find(t => t.key === tab).statuses;
    const params = {};
    if (searchSector.trim()) params.search = searchSector.trim();
    if (searchStock.trim()) params.stock = searchStock.trim();
    Promise.all(statuses.map(s => listSectorPicks(s, params).catch(() => [])))
      .then(arrs => setPicks(arrs.flat()))
      .catch(e => setErr(String(e)))
      .finally(() => setLoading(false));
  };

  useEffect(load, [tab]);
  // Re-fetch when filters change (debounced by the user typing + pressing Enter)
  const handleSearch = (e) => {
    e.preventDefault();
    load();
  };

  return (
    <div style={{ padding: 24 }}>
      <h2 style={{ marginBottom: 16 }}>📊 板块追踪</h2>
      <div style={{ display: 'flex', gap: 8, marginBottom: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        {TABS.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
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
      </div>

      {/* Filter row */}
      <form onSubmit={handleSearch} style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
        <input
          type="text"
          placeholder="按板块名称筛选..."
          value={searchSector}
          onChange={e => setSearchSector(e.target.value)}
          style={{
            padding: '6px 10px', border: '1px solid #ccc', borderRadius: 4,
            fontSize: 13, width: 180,
          }}
        />
        <input
          type="text"
          placeholder="按股票代码/名称筛选..."
          value={searchStock}
          onChange={e => setSearchStock(e.target.value)}
          style={{
            padding: '6px 10px', border: '1px solid #ccc', borderRadius: 4,
            fontSize: 13, width: 180,
          }}
        />
        <button type="submit" style={{
          padding: '6px 14px', background: '#1565c0', color: '#fff',
          border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 13,
        }}>
          筛选
        </button>
        {(searchSector || searchStock) && (
          <button type="button" onClick={() => { setSearchSector(''); setSearchStock(''); }} style={{
            padding: '6px 10px', background: '#fff', color: '#666',
            border: '1px solid #ccc', borderRadius: 4, cursor: 'pointer', fontSize: 12,
          }}>
            清除
          </button>
        )}
      </form>

      {loading && <div>加载中…</div>}
      {err && <div style={{ color: 'red' }}>{err}</div>}

      {!loading && picks.length === 0 && (
        <div style={{ color: '#888', padding: 24, textAlign: 'center' }}>
          还没有追踪板块，去 Telegram bot 发送「📊 板块追踪」试试
        </div>
      )}

      {!loading && picks.length > 0 && (
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: '#37474f', color: '#fff' }}>
              <th style={th}>板块</th>
              <th style={th}>状态</th>
              <th style={th}>数据源</th>
              <th style={th}>创建时间</th>
              <th style={th}>板块 T+3</th>
              <th style={th}>板块 T+5</th>
              <th style={th}>板块 T+10</th>
              <th style={th}>板块 T+20</th>
              <th style={{...th, width: 50}}></th>
            </tr>
          </thead>
          <tbody>
            {picks.map(p => {
              const isExpanded = expandedIds.has(p.id);
              const detail = detailCache[p.id];
              return (
              <React.Fragment key={p.id}>
                <tr
                  style={{ borderBottom: '1px solid #eee', cursor: 'pointer' }}
                  onClick={() => toggleExpand(p.id)}
                >
                  <td style={{ ...td, fontWeight: 600 }}>
                    <span style={{ marginRight: 6 }}>{isExpanded ? '▾' : '▸'}</span>
                    {p.sector_name}
                  </td>
                  <td style={td}><StatusBadge status={p.status} /></td>
                  <td style={td}>{p.selection_source === 'api_driven' ? 'API 实时' : 'AI 知识'}</td>
                  <td style={td}>{new Date(p.created_at).toLocaleString()}</td>
                  <td style={td}><Pct value={p.avg_t3_pct} /></td>
                  <td style={td}><Pct value={p.avg_t5_pct} /></td>
                  <td style={td}><Pct value={p.avg_t10_pct} /></td>
                  <td style={td}><Pct value={p.avg_t20_pct} /></td>
                  <td style={{...td, padding: '4px'}} onClick={e => e.stopPropagation()}>
                    <button
                      onClick={() => handleDelete(p.id, p.sector_name)}
                      title="删除板块"
                      style={{
                        background: 'rgba(211,47,47,0.1)', color: '#d32f2f',
                        border: '1px solid rgba(211,47,47,0.3)', borderRadius: 4,
                        cursor: 'pointer', fontSize: 13, padding: '2px 6px', lineHeight: 1,
                      }}
                    >✕</button>
                  </td>
                </tr>
                {isExpanded && (
                  <tr>
                    <td colSpan={9} style={{ padding: '12px 20px' }}>
                      {detail?.loading ? (
                        <div style={{ color: '#888', padding: 16 }}>加载中…</div>
                      ) : detail?.error ? (
                        <div style={{ color: '#d32f2f', padding: 16 }}>加载失败: {detail.error}</div>
                      ) : detail?.data ? (
                        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                          <thead>
                            <tr style={{ background: '#37474f' }}>
                              <th style={th}>代码</th>
                              <th style={th}>名称</th>
                              <th style={th}>入选理由</th>
                              <th style={th}>T0价</th>
                              <th style={th}>T+3</th>
                              <th style={th}>T+5</th>
                              <th style={th}>T+10</th>
                              <th style={th}>T+20</th>
                            </tr>
                          </thead>
                          <tbody>
                            {detail.data.stocks.map((s, i) => (
                              <tr key={i} style={{ borderBottom: '1px solid #e8eaf0' }}>
                                <td style={td}><span style={{fontFamily:'monospace',fontSize:13}}>{s.code}</span></td>
                                <td style={{...td, fontWeight:600}}>{s.name}</td>
                                <td style={{...td, fontSize:12}}>{s.reason || '—'}</td>
                                <td style={td}>{s.t0_price != null ? s.t0_price.toFixed(2) : '—'}</td>
                                <td style={td}><Pct value={s.t3_pct} /></td>
                                <td style={td}><Pct value={s.t5_pct} /></td>
                                <td style={td}><Pct value={s.t10_pct} /></td>
                                <td style={td}><Pct value={s.t20_pct} /></td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      ) : null}
                    </td>
                  </tr>
                )}
              </React.Fragment>
              );
            })}
          </tbody>
        </table>
      )}
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
      padding: '2px 8px',
      background: cfg.bg,
      color: cfg.color,
      borderRadius: 4,
      fontSize: 12,
    }}>
      {cfg.label}
    </span>
  );
}

function Pct({ value }) {
  if (value == null) return <span style={{ color: '#999' }}>—</span>;
  const isPos = value > 0;
  const isNeg = value < 0;
  const color = isPos ? '#d32f2f' : isNeg ? '#2e7d32' : '#333';
  return <span style={{ color, fontWeight: 600 }}>{value > 0 ? '+' : ''}{value.toFixed(2)}%</span>;
}

const th = { padding: '8px 12px', textAlign: 'left', fontSize: 13, color: '#fff' };
const td = { padding: '8px 12px', fontSize: 14 };
