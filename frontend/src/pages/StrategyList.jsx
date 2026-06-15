import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { listStrategyPicks } from '../api/strategy.js';
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

  useEffect(() => {
    setLoading(true);
    setErr(null);
    const statuses = TABS.find(t => t.key === tab).statuses;
    Promise.all([
      ...statuses.map(s => listStrategyPicks(s, filterStrategyId).catch(() => [])),
      listStrategies().catch(() => []),
    ]).then(([picksArr, strats]) => {
      setPicks(picksArr.flat());
      setStrategies(strats);
    })
    .catch(e => setErr(String(e)))
    .finally(() => setLoading(false));
  }, [tab, filterStrategyId]);

  const strategyName = (id, name) => name || strategies.find(s => s.id === id)?.name || `#${id}`;

  return (
    <div style={{ padding: 24 }}>
      <h2 style={{ marginBottom: 16 }}>🎯 策略追踪（连续三日流入）</h2>
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
          {tab === 'active'
            ? '还没有策略批次。每天 14:30 自动跑 iwencai 选股，结果会出现在这里。'
            : '没有归档批次。'}
        </div>
      )}

      {!loading && picks.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {picks.map(p => (
            <PickCard key={p.id} pick={p} strategyName={strategyName} />
          ))}
        </div>
      )}
    </div>
  );
}

function PickCard({ pick, strategyName }) {
  const preview = pick.stocks_preview || [];
  const hidden = pick.hit_count - preview.length;
  return (
    <div style={{
      background: '#fff', border: '1px solid #e0e0e0', borderRadius: 8,
      padding: 16, boxShadow: '0 1px 2px rgba(0,0,0,0.04)',
    }}>
      {/* header row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 10, flexWrap: 'wrap' }}>
        <Link to={`/strategy/${pick.id}`} style={{ fontSize: 16, fontWeight: 700, color: '#1565c0' }}>
          #{pick.id}
        </Link>
        <span style={{ fontSize: 14, color: '#333' }}>{strategyName(pick.strategy_id, pick.strategy_name)}</span>
        <StatusBadge status={pick.status} />
        <span style={{ fontSize: 12, color: '#888' }}>
          {new Date(pick.created_at).toLocaleString()}
        </span>
        <span style={{ fontSize: 12, color: '#666' }}>
          命中 <b style={{ color: '#1565c0' }}>{pick.hit_count}</b> 只
        </span>
        <div style={{ flex: 1 }} />
        <AvgCells pick={pick} />
      </div>

      {/* query text */}
      {pick.query_text && (
        <div style={{
          fontFamily: 'monospace', fontSize: 11, color: '#666',
          background: '#f7f7f7', padding: '6px 10px', borderRadius: 4,
          marginBottom: 10, wordBreak: 'break-all', lineHeight: 1.5,
        }}>
          {pick.query_text}
        </div>
      )}

      {/* stock preview table */}
      {preview.length > 0 ? (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: '#eceff1', color: '#37474f' }}>
              <th style={th}>代码</th>
              <th style={th}>名称</th>
              <th style={th}>行业</th>
              <th style={th}>选入价</th>
              <th style={th}>T+3</th>
              <th style={th}>T+7</th>
              <th style={th}>T+15</th>
              <th style={th}>T+30</th>
            </tr>
          </thead>
          <tbody>
            {preview.map(s => (
              <tr key={s.id} style={{ borderBottom: '1px solid #f0f0f0' }}>
                <td style={td}><code style={{ fontSize: 12 }}>{s.stock_code}</code></td>
                <td style={{ ...td, fontWeight: 600 }}>{s.stock_name}</td>
                <td style={td}><span style={{ color: s.industry ? '#555' : '#bbb', fontSize: 12 }}>{s.industry || '—'}</span></td>
                <td style={td}>{s.t0_price != null ? s.t0_price.toFixed(2) : '—'}</td>
                <td style={td}><Pct value={s.t3_pct} /></td>
                <td style={td}><Pct value={s.t7_pct} /></td>
                <td style={td}><Pct value={s.t15_pct} /></td>
                <td style={td}><Pct value={s.t30_pct} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div style={{ color: '#999', fontSize: 12, padding: '6px 0' }}>该批次没有股票记录</div>
      )}

      {hidden > 0 && (
        <div style={{ marginTop: 6, fontSize: 12, color: '#1565c0' }}>
          还有 {hidden} 只未显示 — <Link to={`/strategy/${pick.id}`}>查看全部</Link>
        </div>
      )}
    </div>
  );
}

function AvgCells({ pick }) {
  const cells = [
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
  if (value == null) return <span style={{ color: '#bbb', fontSize: small ? 12 : 13 }}>—</span>;
  const isPos = value > 0;
  const isNeg = value < 0;
  const color = isPos ? '#d32f2f' : isNeg ? '#2e7d32' : '#666';
  return (
    <span style={{ color, fontWeight: 600, fontSize: small ? 12 : 13 }}>
      {value > 0 ? '+' : ''}{value.toFixed(2)}%
    </span>
  );
}

const th = { padding: '6px 10px', textAlign: 'left', fontSize: 12, fontWeight: 600 };
const td = { padding: '6px 10px', fontSize: 13 };
