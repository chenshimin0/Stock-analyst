import { useState } from 'react';
import { useReports } from '../hooks/useReports';
import { reportAPI } from '../api/client';
import SortControls from '../components/SortControls';
import ReportCard from '../components/ReportCard';

export default function Dashboard() {
  const [sortKey, setSortKey] = useState('date');
  const [order, setOrder] = useState('desc');
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [searchInput, setSearchInput] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const pageSize = 20;
  const { reports, total, totalPages, loading, error, refetch } = useReports({
    refreshInterval: 30000,
    sort: sortKey,
    order,
    page,
    pageSize,
    search,
  });

  const handleRefreshPrices = async () => {
    setRefreshing(true);
    try {
      const result = await reportAPI.refreshPrices();
      alert(`价格刷新完成：已更新 ${result.updated} 条报告`);
      refetch();
    } catch (e) {
      alert('刷新失败：' + e.message);
    } finally {
      setRefreshing(false);
    }
  };

  const handleSearch = (e) => {
    e.preventDefault();
    setSearch(searchInput.trim());
    setPage(1);
  };

  if (loading) return <div className="loading">加载中...</div>;
  if (error) return <div className="loading" style={{color:'var(--red)'}}>加载失败: {error}</div>;

  return (
    <>
      <div className="page-header">
        <h1>我的分析报告</h1>
        <div style={{display:'flex',alignItems:'center',gap:16,flexWrap:'wrap'}}>
          <form onSubmit={handleSearch} style={{display:'flex',gap:6}}>
            <input
              type="text"
              className="search-input"
              placeholder="搜索股票名称或代码..."
              value={searchInput}
              onChange={e => setSearchInput(e.target.value)}
            />
            <button type="submit" className="search-btn">搜索</button>
            {search && (
              <button type="button" className="search-clear" onClick={() => { setSearchInput(''); setSearch(''); setPage(1); }}>清除</button>
            )}
          </form>
          <button
            className="refresh-btn"
            onClick={handleRefreshPrices}
            disabled={refreshing}
          >
            {refreshing ? '刷新中...' : '刷新报告日收盘价'}
          </button>
          <span className="refresh-indicator">
            <span className="dot"></span> 实时刷新中
          </span>
          <SortControls
            sortKey={sortKey}
            order={order}
            onSort={(key) => { setSortKey(key); setPage(1); }}
            onOrderToggle={() => setOrder(o => o === 'desc' ? 'asc' : 'desc')}
          />
        </div>
      </div>

      {reports.length === 0 ? (
        <div className="empty">
          <h3>暂无报告</h3>
          <p>创建一份股票分析报告来开始</p>
        </div>
      ) : (
        <>
          <div className="report-grid">
            {reports.map(r => <ReportCard key={r.id} report={r} />)}
          </div>

          {totalPages > 1 && (
            <div className="pagination">
              <button
                className="page-btn"
                disabled={page <= 1}
                onClick={() => setPage(page - 1)}
              >
                上一页
              </button>
              <span className="page-info">
                第 {page} / {totalPages} 页（共 {total} 份报告）
              </span>
              <button
                className="page-btn"
                disabled={page >= totalPages}
                onClick={() => setPage(page + 1)}
              >
                下一页
              </button>
            </div>
          )}
        </>
      )}
    </>
  );
}
