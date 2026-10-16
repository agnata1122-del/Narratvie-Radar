/** 데이터가 없을 때의 레이더 그림. 스윕이 돌고 점 몇 개가 깜빡인다 (움직임 줄이기 설정이면 멈춘다). */
export default function EmptyRadar() {
  const blips = [
    { x: 62, y: 38, d: 0 },
    { x: 34, y: 58, d: 1.1 },
    { x: 70, y: 66, d: 2.2 },
  ]
  return (
    <svg width="132" height="132" viewBox="0 0 100 100" aria-hidden="true" className="text-nr-text">
      <defs>
        <linearGradient id="nr-sweep-fill" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="currentColor" stopOpacity="0" />
          <stop offset="1" stopColor="currentColor" stopOpacity="0.18" />
        </linearGradient>
      </defs>
      {[46, 32, 18].map((r) => (
        <circle key={r} cx="50" cy="50" r={r} fill="none" stroke="currentColor" strokeOpacity="0.14" />
      ))}
      <path d="M50 4v92M4 50h92" stroke="currentColor" strokeOpacity="0.08" />
      <g style={{ transformOrigin: '50px 50px', animation: 'nr-sweep 4s linear infinite' }}>
        <path d="M50 50 L50 4 A46 46 0 0 1 89.8 27 Z" fill="url(#nr-sweep-fill)" />
        <path d="M50 50 L89.8 27" stroke="currentColor" strokeOpacity="0.5" strokeWidth="0.8" />
      </g>
      {blips.map((b) => (
        <circle
          key={b.d}
          cx={b.x}
          cy={b.y}
          r="2"
          fill="var(--nr-series-concept)"
          style={{ animation: `nr-blip 4s ease-out ${b.d}s infinite` }}
        />
      ))}
      <circle cx="50" cy="50" r="2.2" fill="currentColor" />
    </svg>
  )
}
