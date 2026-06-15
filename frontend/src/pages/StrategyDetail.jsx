import { useEffect, useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { getStrategyPick, archiveStrategyPick, deleteStrategyPick } from '../api/strategy.js';

export default function StrategyDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [pick, setPick] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);

  useEffect(() => {
    setLoading(true);
    getStrategyPick(id)
      .then(setPick)
      .catch(e => setErr(String(e)))
      .finally(() => setLoading(false));
  }, [id]);

  const handleArchive = async () => {
    if (!confirm(`确认归档批次 #${pick.id}？`)) return;
    await archiveStrategyPick(id);
    navigate('/strategy');
  };

  const handleDelete = async () => {
    if (!confirm(`确认永久删除批次 #${pick.id}？\n该批次 ${pick.hit_count} 只股票的 T+N 追踪数据将全部丢失，无法恢复。`)) return;
    try {
      await deleteStrategyPick(id);
      navigate('/strategy');
    } catch (e) {
      alert('删除失败：' + e.message);
    }
  };

  if (loading) return <div style={{ padding: 24 }}>加载中…</div>;
  if (err) return <div style={{ padding: 24, color: 'red' }}>{err}</div>;
  if (!pick) return <div style={{ padding: 24 }}>未找到该批次</div>;

  return (
    <div style={{ padding: 24 }}>
      <div style={{ marginBottom: 16 }}>
        <Link to="/strategy">← 返回列表</Link>
      </div>

      <h2>策略批次 #{pick.id} — {pick.strategy_name}</h2>

      <div style={{ marginBottom: 16, color: '#666', fontSize: 13 }}>
        <div>创建时间：{new Date(pick.created_at).toLocaleString()}</div>
        <div>状态：{statusLabel(pick.status)}</div>
        <div>命中：{pick.hit_count} 只</div>
        {pick.completed_at && <div>完成时间：{new Date(pick.completed_at).toLocaleString()}</div>}
      </div>

      <div style={{
        background: '#f5f5f5', padding: 10, borderRadius: 4,
        marginBottom: 16, fontSize: 12, color: '#555',
      }}>
        <div style={{ fontWeight: 600, marginBottom: 4 }}>查询条件：</div>
        <div style={{ fontFamily: 'monospace' }}>{pick.query_text}</div>
      </div>

      <h3 style={{ marginBottom: 12 }}>📈 T+N 涨跌幅</h3>
      {pick.stocks && pick.stocks.length > 0 ? (
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: '#37474f', color: '#fff' }}>
              <th style={th}>代码</th>
              <th style={th}>名称</th>
              <th style={th}>行业</th>
              <th style={th}>主营</th>
              <th style={th}>选入价</th>
              <th style={th}>T+3</th>
              <th style={th}>T+7</th>
              <th style={th}>T+15</th>
              <th style={th}>T+30</th>
            </tr>
          </thead>
          <tbody>
            {pick.stocks.map(s => (
              <tr key={s.id} style={{ borderBottom: '1px solid #eee' }}>
                <td style={td}>{s.stock_code}</td>
                <td style={td}>{s.stock_name}</td>
                <td style={td}>{s.industry || <span style={{color:'#999'}}>—</span>}</td>
                <td style={{...td, fontSize: 12, maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'}}
                    title={s.business_summary || ''}>
                  {s.business_summary || <span style={{color:'#999'}}>—</span>}
                </td>
                <td style={td}>{s.t0_price?.toFixed(2) || '—'}</td>
                <td style={td}><Pct value={s.t3_pct} sub={s.t3_date} /></td>
                <td style={td}><Pct value={s.t7_pct} sub={s.t7_date} /></td>
                <td style={td}><Pct value={s.t15_pct} sub={s.t15_date} /></td>
                <td style={td}><Pct value={s.t30_pct} sub={s.t30_date} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div style={{ color: '#888' }}>该批次没有股票记录</div>
      )}

      <div style={{ marginTop: 24, display: 'flex', gap: 10 }}>
        {pick.status !== 'archived' && (
          <button
            onClick={handleArchive}
            style={{
              padding: '8px 18px', background: '#fff',
              border: '1px solid #d32f2f', color: '#d32f2f',
              borderRadius: 4, cursor: 'pointer',
            }}
          >
            归档该批次
          </button>
        )}
        <button
          onClick={handleDelete}
          style={{
            padding: '8px 18px', background: '#fff',
            border: '1px solid #888', color: '#333',
            borderRadius: 4, cursor: 'pointer', fontWeight: 600,
          }}
        >
          🗑️ 永久删除
        </button>
      </div>
    </div>
  );
}

function statusLabel(s) {
  return { in_progress: '进行中', completed: '已完成', archived: '已归档' }[s] || s;
}

function Pct({ value, sub }) {
  if (value == null) return <span style={{ color: '#999' }}>{sub ? `(${sub})` : '—'}</span>;
  const isPos = value > 0;
  const isNeg = value < 0;
  const color = isPos ? '#d32f2f' : isNeg ? '#2e7d32' : '#333';
  return (
    <div style={{ fontSize: 13 }}>
      <span style={{ color, fontWeight: 600 }}>{value > 0 ? '+' : ''}{value.toFixed(2)}%</span>
      {sub && <div style={{ fontSize: 10, color: '#999' }}>{sub}</div>}
    </div>
  );
}

const th = { padding: '8px 12px', textAlign: 'left', fontSize: 13, color: '#fff' };
const td = { padding: '8px 12px', fontSize: 14 };
