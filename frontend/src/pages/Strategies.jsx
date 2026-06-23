import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  listStrategies, createStrategy, updateStrategy,
  deleteStrategy, toggleStrategy, runStrategyNow,
} from '../api/strategies.js';

const EMPTY_FORM = { name: '', query_text: '', schedule_cron: '14:30', enabled: true };

export default function Strategies() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);
  const [editing, setEditing] = useState(null);  // null | 'new' | {id, ...}
  const [runMsg, setRunMsg] = useState(null);

  const load = () => {
    setLoading(true);
    setErr(null);
    listStrategies()
      .then(setItems)
      .catch(e => setErr(String(e)))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const handleSave = async (form) => {
    try {
      if (editing === 'new') {
        await createStrategy(form);
      } else if (editing && editing.id) {
        await updateStrategy(editing.id, form);
      }
      setEditing(null);
      load();
    } catch (e) {
      alert(`保存失败: ${e.message || e}`);
    }
  };

  const handleDelete = async (s) => {
    if (!confirm(`确认删除策略 "${s.name}" 及其所有批次？\n此操作不可恢复。`)) return;
    try {
      await deleteStrategy(s.id);
      load();
    } catch (e) {
      alert(`删除失败: ${e.message || e}`);
    }
  };

  const handleToggle = async (s) => {
    try {
      await toggleStrategy(s.id);
      load();
    } catch (e) {
      alert(`操作失败: ${e.message || e}`);
    }
  };

  const handleRun = async (s) => {
    setRunMsg({ id: s.id, status: 'running' });
    try {
      const r = await runStrategyNow(s.id);
      setRunMsg({ id: s.id, status: 'done', ...r });
      load();
    } catch (e) {
      setRunMsg({ id: s.id, status: 'error', message: e.message || String(e) });
    }
    setTimeout(() => setRunMsg(null), 6000);
  };

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>🎯 策略定义</h2>
        <button onClick={() => setEditing('new')}
                style={{ padding: '8px 16px', background: '#1565c0', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer' }}>
          + 新建策略
        </button>
      </div>

      {loading && <div>加载中…</div>}
      {err && <div style={{ color: 'red' }}>{err}</div>}

      {!loading && items.length === 0 && (
        <div style={{ color: '#888', padding: 24, textAlign: 'center' }}>
          还没有策略。点击右上角"+ 新建策略"开始。
        </div>
      )}

      {!loading && items.length > 0 && (
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: '#37474f', color: '#fff' }}>
              <th style={th}>ID</th>
              <th style={th}>名称</th>
              <th style={th}>调度</th>
              <th style={th}>状态</th>
              <th style={th}>批次</th>
              <th style={th}>上次跑批</th>
              <th style={th}>操作</th>
            </tr>
          </thead>
          <tbody>
            {items.map(s => (
              <tr key={s.id} style={{ borderBottom: '1px solid #eee' }}>
                <td style={td}>#{s.id}</td>
                <td style={td}><b>{s.name}</b></td>
                <td style={{...td, fontSize: 13}}>工作日 {s.schedule_cron.replace(/,/g, ', ')}</td>
                <td style={td}>
                  <span style={{
                    padding: '2px 8px', borderRadius: 4, fontSize: 12,
                    background: s.enabled ? '#e8f5e9' : '#f5f5f5',
                    color: s.enabled ? '#2e7d32' : '#666',
                  }}>{s.enabled ? '启用' : '停用'}</span>
                </td>
                <td style={td}>{s.total_picks}</td>
                <td style={td}>{s.last_pick_at ? new Date(s.last_pick_at).toLocaleString() : '—'}</td>
                <td style={{ ...td, whiteSpace: 'nowrap' }}>
                  <button onClick={() => handleRun(s)}
                          disabled={runMsg?.id === s.id && runMsg?.status === 'running'}
                          style={btnPrimary}>
                    {runMsg?.id === s.id && runMsg?.status === 'running' ? '跑批中…' : '▶ 立即跑'}
                  </button>{' '}
                  <button onClick={() => handleToggle(s)} style={btn}>
                    {s.enabled ? '停用' : '启用'}
                  </button>{' '}
                  <button onClick={() => setEditing({ id: s.id, ...s })} style={btn}>编辑</button>{' '}
                  <button onClick={() => handleDelete(s)} style={btnDanger}>删除</button>{' '}
                  {s.total_picks > 0 && (
                    <Link to={`/strategy?strategy_id=${s.id}`} style={{ marginLeft: 8, fontSize: 12 }}>查看批次 →</Link>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {runMsg && runMsg.status === 'done' && (
        <div style={{ marginTop: 16, padding: 10, background: '#e8f5e9', color: '#2e7d32', borderRadius: 4 }}>
          ✓ {runMsg.message || `已创建 batch #${runMsg.batch_id}（命中 ${runMsg.hit_count}）`}
        </div>
      )}
      {runMsg && runMsg.status === 'error' && (
        <div style={{ marginTop: 16, padding: 10, background: '#ffebee', color: '#c62828', borderRadius: 4 }}>
          ✗ 失败: {runMsg.message}
        </div>
      )}
      {runMsg && runMsg.status === 'done' && runMsg.ok === false && (
        <div style={{ marginTop: 16, padding: 10, background: '#fff3e0', color: '#e65100', borderRadius: 4 }}>
          ⚠ {runMsg.message}
        </div>
      )}

      {editing && (
        <StrategyForm
          key={editing === 'new' ? 'new' : editing.id}
          initial={editing === 'new' ? EMPTY_FORM : {
            name: editing.name, query_text: editing.query_text,
            schedule_cron: editing.schedule_cron, enabled: editing.enabled,
          }}
          onSave={handleSave}
          onCancel={() => setEditing(null)}
        />
      )}
    </div>
  );
}

function StrategyForm({ initial, onSave, onCancel }) {
  const [form, setForm] = useState(initial);
  return (
    <div style={{ marginTop: 24, padding: 16, background: '#f5f5f5', borderRadius: 6 }}>
      <h3 style={{ marginTop: 0 }}>{initial.id ? '编辑策略' : '新建策略'}</h3>
      <div style={{ marginBottom: 12 }}>
        <label style={label}>名称<br/>
          <input style={input} value={form.name} onChange={e => setForm({...form, name: e.target.value})} />
        </label>
      </div>
      <div style={{ marginBottom: 12 }}>
        <label style={label}>iwencai query (用 ; 分隔条件)<br/>
          <textarea style={{...input, height: 80, fontFamily: 'monospace', fontSize: 12}}
                    value={form.query_text} onChange={e => setForm({...form, query_text: e.target.value})} />
        </label>
      </div>
      <div style={{ marginBottom: 12 }}>
        <label style={label}>调度时间 (HH:MM, 逗号分隔多个, 工作日)<br/>
          <input style={{...input, width: 180}} value={form.schedule_cron}
                 placeholder="09:35,14:45"
                 onChange={e => setForm({...form, schedule_cron: e.target.value})} />
        </label>
      </div>
      <div style={{ marginBottom: 12 }}>
        <label>
          <input type="checkbox" checked={form.enabled}
                 onChange={e => setForm({...form, enabled: e.target.checked})} />
          {' '}启用
        </label>
      </div>
      <button onClick={() => onSave(form)}
              disabled={!form.name || !form.query_text}
              style={{ padding: '8px 16px', background: '#1565c0', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer' }}>
        保存
      </button>{' '}
      <button onClick={onCancel} style={{ padding: '8px 16px', background: '#fff', border: '1px solid #ccc', borderRadius: 4, cursor: 'pointer' }}>
        取消
      </button>
    </div>
  );
}

const th = { padding: '8px 12px', textAlign: 'left', fontSize: 13, color: '#fff' };
const td = { padding: '8px 12px', fontSize: 14 };
const label = { fontSize: 12, color: '#666', display: 'block' };
const input = { padding: '6px 10px', border: '1px solid #ccc', borderRadius: 4, fontSize: 14, width: '100%', marginTop: 4 };
const btn = { padding: '4px 10px', background: '#fff', border: '1px solid #ccc', borderRadius: 4, cursor: 'pointer', fontSize: 12 };
const btnPrimary = { ...btn, background: '#1565c0', color: '#fff', border: 'none' };
const btnDanger = { ...btn, background: '#fff', color: '#d32f2f', border: '1px solid #d32f2f' };
