import { NODE_TYPES } from '../lib/graphStyle'
import { NODE_TYPE_LABEL } from '../lib/labels'

/** PRD 11.2–11.3 시각 인코딩 범례 */
export default function Legend() {
  return (
    <div className="pointer-events-none absolute bottom-2 left-2 max-w-[calc(100%-1rem)] rounded border border-nr-border bg-nr-surface/90 px-2 py-1.5 text-[11px] text-nr-muted">
      <div className="flex flex-wrap gap-x-2 gap-y-0.5">
        {NODE_TYPES.map((t) => (
          <span key={t} className="flex items-center gap-1">
            <span className="inline-block size-2 rounded-full" style={{ background: `var(--nr-node-${t})` }} />
            {NODE_TYPE_LABEL[t]}
          </span>
        ))}
        <span className="flex items-center gap-1">
          <span className="inline-block size-2 rounded-full" style={{ background: 'var(--nr-node-dormant)' }} />
          휴면
        </span>
      </div>
      <div className="mt-0.5 flex flex-wrap gap-x-2 gap-y-0.5">
        <span className="flex items-center gap-1">
          <span className="inline-block h-0.5 w-4" style={{ background: 'var(--nr-edge-confirmed)' }} />
          관측 확정
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block h-px w-4 opacity-60" style={{ background: 'var(--nr-edge-candidate)' }} />
          발견 후보
        </span>
        <span>크기 = 관심도 · 흐림 = 검토 대기</span>
      </div>
    </div>
  )
}
