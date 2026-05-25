import { useState } from 'react';
import { useReports } from '../hooks/useReports';
import SortControls from '../components/SortControls';
import ReportCard from '../components/ReportCard';

export default function Dashboard() {
  const [sortKey, setSortKey] = useState('total_score');
  const { reports, loading, error } = useReports({ refreshInterval: 30000, sort: sortKey, order: 'desc' });

  if (loading) return <div className="loading">加载中...</div>;
  if (error) return <div className="loading" style={{color:'var(--red)'}}>加载失败: {error}</div>;

  return (
    <>
      <div className="page-header">
        <h1>我的分析报告</h1>
        <div style={{display:'flex',alignItems:'center',gap:16}}>
          <span className="refresh-indicator">
            <span className="dot"></span> 实时刷新中
          </span>
          <SortControls sortKey={sortKey} onSort={setSortKey} />
        </div>
      </div>

      {reports.length === 0 ? (
        <div className="empty">
          <h3>暂无报告</h3>
          <p>创建一份股票分析报告来开始</p>
        </div>
      ) : (
        <div className="report-grid">
          {reports.map(r => <ReportCard key={r.id} report={r} />)}
        </div>
      )}
    </>
  );
}
