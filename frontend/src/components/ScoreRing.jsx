export default function ScoreRing({ score, size = 64, strokeWidth = 4 }) {
  const radius = (size - strokeWidth * 2) / 2;
  const circumference = radius * 2 * Math.PI;
  const offset = circumference - (score / 100) * circumference;
  const color = score >= 60 ? 'var(--green)' : score >= 40 ? 'var(--yellow)' : 'var(--red)';

  return (
    <div className="score-module">
      <div style={{position:'relative',width:size,height:size,margin:'0 auto'}}>
        <svg width={size} height={size} className="score-ring-svg">
          <circle cx={size/2} cy={size/2} r={radius} fill="none" stroke="#2a2d38" strokeWidth={strokeWidth} />
          <circle cx={size/2} cy={size/2} r={radius} fill="none" stroke={color} strokeWidth={strokeWidth}
            strokeDasharray={circumference} strokeDashoffset={offset} strokeLinecap="round"
            style={{transition:'stroke-dashoffset 0.8s ease'}} />
        </svg>
        <div style={{position:'absolute',top:0,left:0,width:size,height:size,
          display:'flex',alignItems:'center',justifyContent:'center',
          fontSize:size*0.28,fontWeight:700,color}}>
          {score}
        </div>
      </div>
    </div>
  );
}
