import type { PriceSeries } from '../api'
import { changeSince, changeTone, formatChange, sparkPath, visibleBars } from '../lib/prices'

const TONE_CLASS = { up: 'text-nr-up', down: 'text-nr-down', flat: 'text-nr-muted' } as const

export function MarketBadge({ market }: { market: PriceSeries['market'] }) {
  return (
    <span
      className="rounded-[4px] bg-nr-surface-2 px-1 text-[9px] leading-[14px] font-semibold tracking-wide text-nr-text-2 ring-1 ring-nr-border ring-inset"
      title={market === 'US' ? '미국 시장' : '한국 시장'}
    >
      {market}
    </span>
  )
}

type Props = {
  series: PriceSeries[]
  /** 재생 시점. 이때까지 끝난 봉만 그린다 */
  asOf: string
  start: string
  end: string
  /** 지금 프레임의 트리에 있는 노드 */
  presentIds: Set<string>
  selectedId: string | null
  onSelect: (nodeId: string) => void
}

/** 트리에 있는 해외·국내 종목을 같은 시간축과 같은 기준(구간 시작 대비)으로 나란히 본다 (D27) */
export function MarketStrip({ series, asOf, start, end, presentIds, selectedId, onSelect }: Props) {
  const items = series
    .filter((s) => presentIds.has(s.node_id))
    .map((s) => {
      const bars = visibleBars(s.bars, asOf)
      return { s, bars, pct: changeSince(bars, start) }
    })
    .filter((x) => x.bars.length > 0)
  if (items.length === 0) return null

  return (
    <section aria-label="트리 속 종목" className="nr-fade flex items-center gap-3 border-t border-nr-border bg-nr-surface px-4 py-1.5">
      <div className="shrink-0 leading-4">
        <div className="text-[11px] font-semibold text-nr-text">트리 속 종목</div>
        <div className="text-[10px] text-nr-muted">구간 시작 대비 · 일봉 종가</div>
      </div>
      <ul className="flex min-w-0 flex-1 gap-1.5 overflow-x-auto py-0.5">
        {items.map(({ s, bars, pct }) => {
          const tone = changeTone(pct)
          const selected = s.node_id === selectedId
          return (
            <li key={s.key} className="shrink-0">
              <button
                type="button"
                aria-pressed={selected}
                aria-label={`${s.label} ${s.market} ${formatChange(pct)}`}
                onClick={() => onSelect(s.node_id)}
                className={`flex items-center gap-1.5 rounded-lg px-2 py-1 ring-1 transition-colors ring-inset ${
                  selected ? 'bg-nr-surface-2 ring-nr-focus' : 'ring-nr-border hover:bg-nr-surface-2'
                }`}
              >
                <MarketBadge market={s.market} />
                <span className="max-w-[9rem] truncate text-xs font-medium text-nr-text">{s.label}</span>
                <svg width={56} height={18} viewBox="0 0 56 18" aria-hidden="true" className={TONE_CLASS[tone]}>
                  <path d={sparkPath(bars, start, end, 56, 18)} fill="none" stroke="currentColor" strokeWidth={1.25} strokeLinejoin="round" />
                </svg>
                <span className={`text-xs font-semibold tabular-nums ${TONE_CLASS[tone]}`}>{formatChange(pct)}</span>
              </button>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
