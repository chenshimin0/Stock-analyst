export default function PriceBadge({ currentPrice, priceAtReport }) {
  if (!currentPrice) return <span className="price-compare"><span className="current" style={{color:'var(--text-secondary)'}}>--</span></span>;

  const changePct = priceAtReport > 0 ? ((currentPrice - priceAtReport) / priceAtReport * 100) : 0;
  const isUp = changePct > 0;
  const isDown = changePct < 0;
  const color = isUp ? 'var(--green)' : isDown ? 'var(--red)' : 'var(--text-secondary)';

  return (
    <div className="price-compare">
      <span className="current" style={{color}}>{currentPrice.toFixed(2)}</span>
      <div className="change-info">
        <span className="pct" style={{color}}>
          {changePct > 0 ? '+' : ''}{changePct.toFixed(2)}%
        </span>
        <br />
        <span className="report-price">报告价 {priceAtReport?.toFixed(2)}</span>
      </div>
    </div>
  );
}
