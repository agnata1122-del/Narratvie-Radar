import type { SVGProps } from 'react'

// 16px 선 아이콘. 색은 currentColor를 따른다.
type P = SVGProps<SVGSVGElement>

function Base({ children, ...p }: P) {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...p}>
      {children}
    </svg>
  )
}

export const PlayIcon = (p: P) => (
  <Base {...p}>
    <path d="M5 3.5v9l7-4.5-7-4.5z" fill="currentColor" stroke="none" />
  </Base>
)
export const PauseIcon = (p: P) => (
  <Base {...p}>
    <path d="M5.5 3.5v9M10.5 3.5v9" strokeWidth="2" />
  </Base>
)
export const StepBackIcon = (p: P) => (
  <Base {...p}>
    <path d="M4 3.5v9M12 3.5 6.5 8l5.5 4.5z" />
  </Base>
)
export const StepForwardIcon = (p: P) => (
  <Base {...p}>
    <path d="M12 3.5v9M4 3.5 9.5 8 4 12.5z" />
  </Base>
)
export const ZoomInIcon = (p: P) => (
  <Base {...p}>
    <path d="M8 3.5v9M3.5 8h9" />
  </Base>
)
export const ZoomOutIcon = (p: P) => (
  <Base {...p}>
    <path d="M3.5 8h9" />
  </Base>
)
export const FitIcon = (p: P) => (
  <Base {...p}>
    <path d="M3 6V3h3M10 3h3v3M13 10v3h-3M6 13H3v-3" />
  </Base>
)
export const SunIcon = (p: P) => (
  <Base {...p}>
    <circle cx="8" cy="8" r="2.75" />
    <path d="M8 1.5v1.5M8 13v1.5M1.5 8H3M13 8h1.5M3.4 3.4l1 1M11.6 11.6l1 1M3.4 12.6l1-1M11.6 4.4l1-1" />
  </Base>
)
export const MoonIcon = (p: P) => (
  <Base {...p}>
    <path d="M13 9.6A5.5 5.5 0 0 1 6.4 3 5.5 5.5 0 1 0 13 9.6z" />
  </Base>
)
export const SystemIcon = (p: P) => (
  <Base {...p}>
    <rect x="2" y="3" width="12" height="8" rx="1.5" />
    <path d="M6 13.5h4" />
  </Base>
)
export const SparkIcon = (p: P) => (
  <Base {...p}>
    <path d="M8 2.5 9.2 6.8 13.5 8 9.2 9.2 8 13.5 6.8 9.2 2.5 8 6.8 6.8z" />
  </Base>
)
export const ShiftIcon = (p: P) => (
  <Base {...p}>
    <path d="M3 5.5h9l-2.5-2.5M13 10.5H4l2.5 2.5" />
  </Base>
)
export const TrendUpIcon = (p: P) => (
  <Base {...p}>
    <path d="M2.5 11.5 6.5 7.5l2.5 2.5 4.5-4.5M10 5.5h3.5V9" />
  </Base>
)
export const TrendDownIcon = (p: P) => (
  <Base {...p}>
    <path d="M2.5 4.5 6.5 8.5 9 6l4.5 4.5M10 10.5h3.5V7" />
  </Base>
)
export const LinkOutIcon = (p: P) => (
  <Base {...p}>
    <path d="M9 3h4v4M13 3 7.5 8.5M11 9.5V13H3V5h3.5" />
  </Base>
)
export const ChevronIcon = (p: P) => (
  <Base {...p}>
    <path d="m6 4 4 4-4 4" />
  </Base>
)
export const WarnIcon = (p: P) => (
  <Base {...p}>
    <path d="M8 2.5 14 13H2z" />
    <path d="M8 6.5v3M8 11.2v.1" />
  </Base>
)

/** 레이더 로고. live면 스윕이 천천히 돈다. */
export function RadarMark({ live = false, size = 20 }: { live?: boolean; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" className="shrink-0">
      <circle cx="12" cy="12" r="10.5" fill="none" stroke="currentColor" strokeOpacity="0.35" strokeWidth="1" />
      <circle cx="12" cy="12" r="6.5" fill="none" stroke="currentColor" strokeOpacity="0.35" strokeWidth="1" />
      <circle cx="12" cy="12" r="1.6" fill="currentColor" />
      <g style={live ? { transformOrigin: '12px 12px', animation: 'nr-sweep 3.2s linear infinite' } : undefined}>
        <path d="M12 12 L12 1.5 A10.5 10.5 0 0 1 21.1 6.75 Z" fill="currentColor" fillOpacity="0.16" />
        <path d="M12 12 L21.1 6.75" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" />
      </g>
      <circle cx="16.5" cy="8.2" r="1.3" fill="var(--nr-series-concept)" />
    </svg>
  )
}
