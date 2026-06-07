import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { listSectorPicks } from '../api/sector.js';

const TABS = [
  { key: 'active', label: '进行中', statuses: ['in_progress', 'completed'] },
  { key: 'archived', label: '已归档', statuses: ['archived'] },
];

export default function SectorList() {
  const [tab, setTab] = useState('active');
  const [picks, setPicks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);

  useEffect(() => {
    setLoading(true);
    setErr(null);
    const statuses = TABS.find(t => t.key === tab).statuses;
    Promise.all(statuses.map(s => listSectorPicks(s).catch(() => [])))
      .then(arrs => setPicks(arrs.flat()))
      .catch(e => setErr(String(e)))
      .finally(() => setLoading(false));
  }, [tab]);

  return (
    <div style={{ padding: 24 }}>
      <h2 style={{ marginBottom: 16 }}>📊 板块追踪</h2>
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
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
              <th style={th}>板块 T+5</th>
              <th style={th}>板块 T+10</th>
              <th style={th}>板块 T+20</th>
            </tr>
          </thead>
          <tbody>
            {picks.map(p => (
              <tr key={p.id} style={{ borderBottom: '1px solid #eee' }}>
                <td style={td}>
                  <Link to={`/sector-tracker/${p.id}`}>{p.sector_name}</Link>
                </td>
                <td style={td}><StatusBadge status={p.status} /></td>
                <td style={td}>{p.selection_source === 'api_driven' ? 'API 实时' : 'AI 知识'}</td>
                <td style={td}>{new Date(p.created_at).toLocaleString()}</td>
                <td style={td}><Pct value={p.avg_t5_pct} /></td>
                <td style={td}><Pct value={p.avg_t10_pct} /></td>
                <td style={td}><Pct value={p.avg_t20_pct} /></td>
              </tr>
            ))}
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
