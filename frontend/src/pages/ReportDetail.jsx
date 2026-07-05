import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';

export default function ReportDetail() {
  const { slug } = useParams();
  const navigate = useNavigate();
  const [html, setHtml] = useState('');
  const [loading, setLoading] = useState(true);
  const [rerunning, setRerunning] = useState(false);

  const handleRerun = async () => {
    setRerunning(true);
    try {
      const r = await fetch(`/api/reports/${slug}/rerun`, { method: 'POST' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      // Poll until report updates
      let attempts = 0;
      while (attempts < 120) {
        await new Promise(resolve => setTimeout(resolve, 3000));
        const check = await fetch(`/api/reports/${slug}?format=html`);
        const newHtml = await check.text();
        if (newHtml !== html && !newHtml.includes('Report not found')) {
          setHtml(newHtml);
          break;
        }
        attempts++;
      }
    } catch (e) {
      alert(`重新分析失败: ${e.message}`);
    } finally {
      setRerunning(false);
    }
  };

  const handleDelete = async () => {
    if (!confirm(`确认删除报告 ${slug}？\n此操作不可恢复。`)) return;
    try {
      const r = await fetch(`/api/reports/${slug}`, { method: 'DELETE' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      alert(`已删除报告 ${slug}`);
      navigate('/');
    } catch (e) {
      alert(`删除失败: ${e.message}`);
    }
  };

  useEffect(() => {
    document.body.classList.add('light-theme');
    fetch(`/api/reports/${slug}?format=html`)
      .then(r => r.text())
      .then(data => setHtml(data))
      .finally(() => setLoading(false));
    return () => document.body.classList.remove('light-theme');
  }, [slug]);

  if (loading) return <div className="loading">加载报告中...</div>;

  return (
    <div className="report-detail-container">
      <button
        onClick={handleRerun}
        disabled={rerunning}
        style={{
          position: 'fixed', top: 72, right: 140, zIndex: 100,
          padding: '6px 14px', background: rerunning ? '#e0e0e0' : 'var(--card-bg)',
          border: '1px solid #1565c0', color: '#1565c0',
          borderRadius: 8, cursor: rerunning ? 'not-allowed' : 'pointer', fontSize: 12, fontWeight: 600,
        }}
      >
        {rerunning ? '⏳ 分析中...' : '🔄 重新分析'}
      </button>
      <button
        onClick={handleDelete}
        style={{
          position: 'fixed', top: 72, right: 24, zIndex: 100,
          padding: '6px 14px', background: 'var(--card-bg)',
          border: '1px solid #d32f2f', color: '#d32f2f',
          borderRadius: 8, cursor: 'pointer', fontSize: 12, fontWeight: 600,
        }}
      >
        🗑️ 删除报告
      </button>
      <iframe srcDoc={html} title="Report" style={{width:'100%',height:'100vh',border:'none',borderRadius:12}} />
    </div>
  );
}