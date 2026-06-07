import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { getSectorPick, archiveSectorPick } from '../api/sector.js';

export default function SectorDetail() {
  const { id } = useParams();
  const [pick, setPick] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);

  const load = () => {
    setLoading(true);
    getSectorPick(id)
      .then(setPick)
      .catch(e => setErr(String(e)))
      .finally(() => setLoading(false));
  };

  useEffect(load, [id]);

  const handleArchive = async () => {
    if (!confirm(`确认归档板块 ${pick.sector_name}？`)) return;
    await archiveSectorPick(id);
    load();
  };

  if (loading) return <div style={{ padding: 24 }}>加载中…</div>;
  if (err) return <div style={{ padding: 24, color: 'red' }}>{err}</div>;
  if (!pick) return <div style={{ padding: 24 }}>未找到该追踪</div>;

  const avgT5 = pick.avg_t5_pct;
  const avgT10 = pick.avg_t10_pct;
  const avgT20 = pick.avg_t20_pct;

  return (
    <div style={{ padding: 24 }}>
      <div style={{ marginBottom: 16 }}>
        <Link to="/sector-tracker">← 返回列表</Link>
      </div>
      <h2 style={{ marginBottom: 8 }}>{pick.sector_name} 板块追踪</h2>
      <div style={{ color: '#666', marginBottom: 16, fontSize: 14 }}>
        状态：<b>{pick.status}</b> · 数据源：{pick.selection_source === 'api_driven' ? 'API 实时' : 'AI 知识'} · 创建时间：{new Date(pick.created_at).toLocaleString()}
        {pick.completed_at && <span> · 完成时间：{new Date(pick.completed_at).toLocaleString()}</span>}
      </div>

      <table style={{ width: '100%', borderCollapse: 'collapse', marginBottom: 16 }}>
        <thead>
          <tr style={{ background: '#37474f', color: '#fff' }}>
            <th style={th}>代码</th>
            <th style={th}>名称</th>
            <th style={th}>推荐理由</th>
            <th style={th}>T+0 价</th>
            <th style={th}>T+5</th>
            <th style={th}>T+10</th>
            <th style={th}>T+20</th>
          </tr>
        </thead>
        <tbody>
          {pick.stocks.map(s => (
            <tr key={s.code} style={{ borderBottom: '1px solid #eee' }}>
              <td style={td}>{s.code}</td>
              <td style={td}>{s.name}</td>
              <td style={td}>{s.reason}</td>
              <td style={td}>{s.t0_price != null ? s.t0_price.toFixed(2) : '—'}</td>
              <td style={td}><Pct value={s.t5_pct} /></td>
              <td style={td}><Pct value={s.t10_pct} /></td>
              <td style={td}><Pct value={s.t20_pct} /></td>
            </tr>
          ))}
          <tr style={{ background: '#fafafa', fontWeight: 600 }}>
            <td style={td} colSpan={4}>板块平均</td>
            <td style={td}><Pct value={avgT5} /></td>
            <td style={td}><Pct value={avgT10} /></td>
            <td style={td}><Pct value={avgT20} /></td>
          </tr>
        </tbody>
      </table>

      {pick.status !== 'archived' && (
        <button
          onClick={handleArchive}
          style={{
            padding: '8px 16px',
            background: '#fff',
            border: '1px solid #ccc',
            borderRadius: 4,
            cursor: 'pointer',
          }}
        >
          归档
        </button>
      )}
    </div>
  );
}

function Pct({ value }) {
  if (value == null) return <span style={{ color: '#999' }}>—</span>;
  const color = value > 0 ? '#d32f2f' : value < 0 ? '#2e7d32' : '#333';
  return <span style={{ color, fontWeight: 600 }}>{value > 0 ? '+' : ''}{value.toFixed(2)}%</span>;
}

const th = { padding: '8px 12px', textAlign: 'left', fontSize: 13, color: '#fff' };
const td = { padding: '8px 12px', fontSize: 14 };
