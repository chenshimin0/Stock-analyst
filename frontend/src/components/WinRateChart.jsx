import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts';

export default function WinRateChart({ data, title }) {
  if (!data || data.length === 0) return <p style={{color:'var(--text-secondary)',textAlign:'center',padding:40}}>暂无胜率数据</p>;

  const chartData = data.map(d => ({
    period: `${d.period_days}天`,
    changePct: d.change_pct != null ? d.change_pct : 0,
    isWin: d.is_win,
  }));

  return (
    <div className="winrate-chart-box">
      {title && <h3>{title}</h3>}
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" stroke="#2a2d38" />
          <XAxis dataKey="period" stroke="#9ca3af" fontSize={13} />
          <YAxis stroke="#9ca3af" fontSize={12} tickFormatter={v => `${v}%`} />
          <Tooltip
            contentStyle={{ background: '#1a1d27', border: '1px solid #2a2d38', borderRadius: 8, color: '#d1d5db' }}
            formatter={(value) => [`${value}%`, '涨跌幅']}
            labelFormatter={(label) => `报告后${label}`}
          />
          <Bar dataKey="changePct" radius={[4, 4, 0, 0]}>
            {chartData.map((entry, i) => (
              <Cell key={i} fill={entry.changePct > 0 ? '#22c55e' : '#ef4444'} fillOpacity={0.8} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
