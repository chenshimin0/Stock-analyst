import { useState, useEffect } from 'react';
import { reportAPI } from '../api/client';
import WinRateChart from '../components/WinRateChart';

const PERIOD_LABELS = { 7: '7天', 15: '15天', 30: '30天', 90: '90天', 180: '180天' };

export default function WinRateAnalysis() {
  const [allData, setAllData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedReport, setSelectedReport] = useState(null);

  useEffect(() => {
    reportAPI.winrateAll().then(data => {
      setAllData(data);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

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
                <th>报告日期</th>
                <th>分析分</th>
                <th>标签</th>
                {Object.entries(PERIOD_LABELS).map(([days, label]) => (
                  <th key={days}>{label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {allData.map(r => (
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
                  {Object.keys(PERIOD_LABELS).map(days => {
                    const p = (r.periods || []).find(p => p.period_days === Number(days));
                    if (!p) return <td key={days}>-</td>;
                    if (p.is_win === null) return <td key={days} style={{color:'var(--text-muted)'}}>待定</td>;
                    return (
                      <td key={days} style={{color: p.is_win ? 'var(--green)' : 'var(--red)'}}>
                        {p.is_win ? '+' : ''}{p.change_pct}%
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
