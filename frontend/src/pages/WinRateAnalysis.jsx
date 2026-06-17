import { useState, useEffect, useMemo } from 'react';
import { reportAPI } from '../api/client';
import WinRateChart from '../components/WinRateChart';

const PERIOD_LABELS = { 7: '7天', 15: '15天', 30: '30天', 90: '90天', 180: '180天' };
const PERIOD_KEYS = Object.keys(PERIOD_LABELS).map(Number);

export default function WinRateAnalysis() {
  const [allData, setAllData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedReport, setSelectedReport] = useState(null);
  const [sortField, setSortField] = useState('report_date');
  const [sortDir, setSortDir] = useState('desc');

  useEffect(() => {
    reportAPI.winrateAll().then(data => {
      setAllData(data);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  const handleSort = (field) => {
    if (sortField === field) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDir(field === 'report_date' || field === 'total_score' ? 'desc' : 'desc');
    }
  };

  const sortedData = useMemo(() => {
    const sorted = [...allData];
    sorted.sort((a, b) => {
      let va, vb;
      if (sortField === 'report_date') {
        va = a.report_date || '';
        vb = b.report_date || '';
      } else if (sortField === 'total_score') {
        va = a.total_score || 0;
        vb = b.total_score || 0;
      } else if (sortField === 'label') {
        va = a.label || '';
        vb = b.label || '';
      } else {
        // Period columns (7, 15, 30, 90, 180)
        const pa = (a.periods || []).find(p => p.period_days === Number(sortField));
        const pb = (b.periods || []).find(p => p.period_days === Number(sortField));
        va = pa?.change_pct;
        vb = pb?.change_pct;
        if (va === null || va === undefined) va = sortDir === 'asc' ? Infinity : -Infinity;
        if (vb === null || vb === undefined) vb = sortDir === 'asc' ? Infinity : -Infinity;
      }
      if (va < vb) return sortDir === 'asc' ? -1 : 1;
      if (va > vb) return sortDir === 'asc' ? 1 : -1;
      return 0;
    });
    return sorted;
  }, [allData, sortField, sortDir]);

  const sortIndicator = (field) => {
    if (sortField !== field) return ' ↕';
    return sortDir === 'asc' ? ' ↑' : ' ↓';
  };

  const selectedData = selectedReport
    ? allData.find(r => r.report_id === selectedReport.report_id)
    : null;

  if (loading) return <div className="loading">加载中...</div>;

  return (
    <div className="winrate-page">
      <div className="page-header">
        <h1>胜率统计分析</h1>
      </div>

      <div className="winrate-charts">
        {selectedData && (
          <WinRateChart
            data={selectedData.periods || []}
            title={`${selectedData.stock_name} 各时间段胜率`}
          />
        )}

        <div className="winrate-chart-box">
          <h3>全部报告胜率一览</h3>
          <table className="winrate-table">
            <thead>
              <tr>
                <th>股票</th>
                <th className="sortable" onClick={() => handleSort('report_date')}>
                  报告日期{sortIndicator('report_date')}
                </th>
                <th className="sortable" onClick={() => handleSort('total_score')}>
                  分析分{sortIndicator('total_score')}
                </th>
                <th className="sortable" onClick={() => handleSort('label')}>
                  标签{sortIndicator('label')}
                </th>
                {PERIOD_KEYS.map(days => (
                  <th key={days} className="sortable" onClick={() => handleSort(String(days))}>
                    {PERIOD_LABELS[days]}{sortIndicator(String(days))}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sortedData.map(r => (
                <tr
                  key={r.report_id}
                  className={selectedReport?.report_id === r.report_id ? 'selected' : ''}
                  onClick={() => setSelectedReport(r)}
                  style={{ cursor: 'pointer' }}
                >
                  <td><strong>{r.stock_name}</strong><br/><small>{r.stock_code}</small></td>
                  <td>{r.report_date}</td>
                  <td>{r.total_score}</td>
                  <td>
                    <span className={`label-tag label-${(r.label || '').toLowerCase()}`}>{r.label}</span>
                  </td>
                  {PERIOD_KEYS.map(days => {
                    const p = (r.periods || []).find(p => p.period_days === days);
                    if (!p) return <td key={days}>-</td>;
                    if (p.is_win === null) return <td key={days} style={{color:'var(--text-muted)'}}>待定</td>;
                    return (
                      <td key={days}>
                        <span className={"win-pct " + (p.is_win ? "win-pos" : "win-neg")}>
                          {p.is_win ? '+' : ''}{p.change_pct}%
                        </span>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          {!selectedReport && (
            <p className="hint">点击某行查看该报告的胜率图表</p>
          )}
        </div>
      </div>
    </div>
  );
}
