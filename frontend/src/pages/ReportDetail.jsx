import { useState, useEffect, useRef } from 'react';
import { useParams } from 'react-router-dom';

const REFRESH_INTERVAL = 30000; // 30秒刷新实时价格

export default function ReportDetail() {
  const { slug } = useParams();
  const [html, setHtml] = useState('');
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState(null);
  const intervalRef = useRef(null);

  const fetchReport = () => {
    fetch(`/api/reports/${slug}?format=html`)
      .then(r => r.text())
      .then(data => {
        setHtml(data);
        setLastRefresh(new Date().toLocaleTimeString('zh-CN', { hour12: false }));
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    document.body.classList.add('light-theme');
    fetchReport();
    intervalRef.current = setInterval(fetchReport, REFRESH_INTERVAL);
    return () => {
      document.body.classList.remove('light-theme');
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [slug]);

  if (loading) return <div className="loading">加载报告中...</div>;

  return (
    <div className="report-detail-container">
      {lastRefresh && (
        <div style={{
          position: 'fixed', top: 72, right: 24, zIndex: 100,
          background: 'var(--card-bg)', border: '1px solid var(--border)',
          borderRadius: 8, padding: '6px 14px', fontSize: 12,
          color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: 8
        }}>
          <span className="dot" style={{ background: 'var(--green)' }}></span>
          实时价格刷新中 · {lastRefresh}
        </div>
      )}
      <iframe srcDoc={html} title="Report" style={{width:'100%',height:'100vh',border:'none',borderRadius:12}} />
    </div>
  );
}