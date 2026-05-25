import { Link } from 'react-router-dom';
import PriceBadge from './PriceBadge';
import ScoreRing from './ScoreRing';

function labelClass(label) {
  if (label === '可做' || label === '买入') return 'label-buy';
  if (label === '回避') return 'label-avoid';
  return 'label-watch';
}

export default function ReportCard({ report }) {
  const totalScore = report.total_score || 0;

  return (
    <Link to={`/reports/${report.slug || report.id}`}>
      <div className="report-card">
        <div className="card-top">
          <div>
            <div className="stock-name">{report.stock_name}</div>
            <div className="stock-code">{report.stock_code} · {report.report_date}</div>
          </div>
          <span className={`label-badge ${labelClass(report.label)}`}>{report.label}</span>
        </div>
        <div className="card-middle">
          <PriceBadge currentPrice={report.current_price} priceAtReport={report.price_at_report} />
          <div style={{textAlign:'center'}}>
            <span style={{fontSize:12,color:'var(--text-secondary)'}}>分析总分</span>
            <ScoreRing score={totalScore} size={56} strokeWidth={3} />
          </div>
        </div>
        <div className="card-bottom">
          <span>短线 {report.momentum_score} · 营收 {report.revenue_score} · 风险 {report.risk_score}</span>
        </div>
      </div>
    </Link>
  );
}
