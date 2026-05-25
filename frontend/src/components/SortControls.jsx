const SORT_OPTIONS = [
  { key: 'total_score', label: '分析总分' },
  { key: 'date', label: '日期' },
];

export default function SortControls({ sortKey, onSort }) {
  return (
    <div className="sort-controls">
      {SORT_OPTIONS.map(opt => (
        <button key={opt.key} className={sortKey === opt.key ? 'active' : ''} onClick={() => onSort(opt.key)}>
          {opt.label}
        </button>
      ))}
    </div>
  );
}
