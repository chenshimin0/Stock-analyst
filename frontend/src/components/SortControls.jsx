const SORT_OPTIONS = [
  { key: 'performance', label: '表现' },
  { key: 'total_score', label: '分析总分' },
  { key: 'date', label: '日期' },
];

export default function SortControls({ sortKey, order, onSort, onOrderToggle }) {
  return (
    <div className="sort-controls">
      {SORT_OPTIONS.map(opt => (
        <button key={opt.key} className={sortKey === opt.key ? 'active' : ''} onClick={() => onSort(opt.key)}>
          {opt.label}
        </button>
      ))}
      <button className="order-toggle" onClick={onOrderToggle} title={order === 'desc' ? '降序' : '升序'}>
        {order === 'desc' ? '↓ 降序' : '↑ 升序'}
      </button>
    </div>
  );
}
