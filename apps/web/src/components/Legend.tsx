import { SERIES_GROUPS } from '../lib/graphStyle'
import { SERIES_LABEL } from '../lib/labels'

function Swatch({ group }: { group: string }) {
  const diamond = group === 'narrative'
  return (
    <span
      className={`inline-block size-2.5 shrink-0 ${diamond ? 'scale-90 rotate-45 rounded-[2px]' : 'rounded-full'}`}
      style={{ background: `var(--nr-series-${group})` }}
    />
  )
}

function Line({ dashed = false, faint = false }: { dashed?: boolean; faint?: boolean }) {
  return (
    <svg width="22" height="6" aria-hidden="true" className="shrink-0">
      <line
        x1="1"
        y1="3"
        x2="21"
        y2="3"
        stroke={faint ? 'var(--nr-edge-candidate)' : 'var(--nr-edge-confirmed)'}
        strokeWidth={dashed ? 1.25 : 2}
        strokeDasharray={dashed ? '3 3' : undefined}
        strokeLinecap="round"
      />
    </svg>
  )
}

/** PRD 11.2–11.3 시각 인코딩 범례. 색만으로 구분하지 않도록 모양·선 종류를 함께 쓴다. */
export default function Legend() {
  return (
    <details
      open
      className="group pointer-events-auto absolute bottom-3 left-3 max-w-[calc(100%-1.5rem)] rounded-lg border border-nr-border bg-nr-surface/90 text-[11px] text-nr-text-2 shadow-nr backdrop-blur"
    >
      <summary className="cursor-pointer list-none px-2.5 py-1.5 font-medium text-nr-muted select-none group-open:pb-0.5">범례</summary>
      <div className="space-y-1 px-2.5 pb-2">
        <div className="flex flex-wrap gap-x-3 gap-y-1">
          {SERIES_GROUPS.map((g) => (
            <span key={g} className="flex items-center gap-1.5">
              <Swatch group={g} />
              {SERIES_LABEL[g]}
            </span>
          ))}
          <span className="flex items-center gap-1.5">
            <span className="inline-block size-2.5 rounded-full" style={{ background: 'var(--nr-node-dormant)' }} />
            휴면
          </span>
        </div>
        <div className="flex flex-wrap gap-x-3 gap-y-1">
          <span className="flex items-center gap-1.5">
            <Line />
            관측 확정
          </span>
          <span className="flex items-center gap-1.5">
            <Line dashed faint />
            발견 후보
          </span>
          <span className="text-nr-muted">크기 = 관심도 · 흐림 = 검토 대기</span>
        </div>
      </div>
    </details>
  )
}
