import type { Gap, GraphEventRow } from '../api'
import { EVENT_TYPE_LABEL, SOURCE_LABEL, label } from '../lib/labels'
import { positionIn } from '../lib/frames'
import { formatTime } from '../lib/time'

export type RangeDays = 3 | 7 | 14 | 30

export type TimelineProps = {
  times: string[]
  index: number
  onIndex: (i: number) => void
  playing: boolean
  onTogglePlay: () => void
  speed: number
  onSpeed: (s: number) => void
  rangeDays: RangeDays
  onRangeDays: (d: RangeDays) => void
  events: GraphEventRow[]
  gaps: Gap[]
  previousSeenAt: string | null
}

function tickClass(type: string): string {
  if (type.startsWith('NARRATIVE')) return 'bg-[var(--nr-node-narrative)]'
  if (type.startsWith('EDGE')) return 'bg-nr-muted'
  if (type === 'WIKI_REVISED') return 'bg-nr-border'
  return 'bg-nr-accent'
}

export default function Timeline(p: TimelineProps) {
  const start = p.times[0]
  const end = p.times[p.times.length - 1]
  const last = p.times.length - 1
  const at = p.times[p.index]
  const shownEvents = p.events.filter((e) => e.type !== 'WIKI_REVISED')

  const button = 'rounded border border-nr-border px-2 py-0.5 text-xs text-nr-text hover:bg-nr-bg disabled:opacity-40'

  return (
    <div className="sticky bottom-0 z-10 border-t border-nr-border bg-nr-surface px-4 py-2 md:static">
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className={button} onClick={() => p.onIndex(Math.max(0, p.index - 1))} disabled={p.index === 0} aria-label="이전 시점">
          ◀
        </button>
        <button type="button" className={`${button} min-w-14`} onClick={p.onTogglePlay} aria-label={p.playing ? '일시 정지' : '재생'}>
          {p.playing ? '일시 정지' : '재생'}
        </button>
        <button type="button" className={button} onClick={() => p.onIndex(Math.min(last, p.index + 1))} disabled={p.index === last} aria-label="다음 시점">
          ▶
        </button>
        <label className="flex items-center gap-1 text-xs text-nr-muted">
          속도
          <select value={p.speed} onChange={(e) => p.onSpeed(Number(e.target.value))} className="rounded border border-nr-border bg-nr-surface px-1 py-0.5 text-xs text-nr-text">
            {[1, 2, 4].map((s) => (
              <option key={s} value={s}>
                {s}×
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1 text-xs text-nr-muted">
          범위
          <select
            value={p.rangeDays}
            onChange={(e) => p.onRangeDays(Number(e.target.value) as RangeDays)}
            className="rounded border border-nr-border bg-nr-surface px-1 py-0.5 text-xs text-nr-text"
          >
            {[3, 7, 14, 30].map((d) => (
              <option key={d} value={d}>
                최근 {d}일
              </option>
            ))}
          </select>
        </label>
        <div className="ml-auto text-sm font-medium text-nr-text tabular-nums" aria-live="polite">
          {at ? formatTime(at) : '—'}
          {p.index === last && <span className="ml-1 text-xs text-nr-muted">(최신)</span>}
        </div>
      </div>

      {start && end && (
        <div className="relative mt-2">
          {/* 관측 공백(빗금)과 그래프 변화(눈금) */}
          <div className="relative h-4" aria-hidden="true">
            {p.gaps.map((g, i) => {
              const a = positionIn(start, end, g.start)
              const b = positionIn(start, end, g.end)
              return (
                <div
                  key={`${g.source_adapter_id}-${i}`}
                  className="absolute top-0 h-full rounded-sm"
                  style={{
                    left: `${a * 100}%`,
                    width: `${Math.max(0.4, (b - a) * 100)}%`,
                    background: 'repeating-linear-gradient(135deg, var(--nr-warn-text) 0 2px, transparent 2px 6px)',
                    opacity: 0.45,
                  }}
                  title={`${label(SOURCE_LABEL, g.source_adapter_id)} 관측 공백 · ${formatTime(g.start)} → ${formatTime(g.end)}`}
                />
              )
            })}
            {shownEvents.map((e, i) => (
              <div
                key={i}
                className={`absolute bottom-0 h-2.5 w-px ${tickClass(e.type)}`}
                style={{ left: `${positionIn(start, end, e.t) * 100}%` }}
                title={`${formatTime(e.t)} · ${label(EVENT_TYPE_LABEL, e.type)}`}
              />
            ))}
            {p.previousSeenAt && new Date(p.previousSeenAt) > new Date(start) && (
              <div
                className="absolute top-0 h-full w-0.5 bg-nr-highlight"
                style={{ left: `${positionIn(start, end, p.previousSeenAt) * 100}%` }}
                title={`지난 방문 ${formatTime(p.previousSeenAt)}`}
              />
            )}
          </div>
          <input
            type="range"
            min={0}
            max={last}
            step={1}
            value={p.index}
            onChange={(e) => p.onIndex(Number(e.target.value))}
            aria-label="재생 시점"
            aria-valuetext={at ? formatTime(at) : undefined}
            className="w-full accent-[var(--nr-accent)]"
          />
          <div className="flex justify-between text-[11px] text-nr-muted tabular-nums">
            <span>{formatTime(start)}</span>
            <span>
              변화 {shownEvents.length}건{p.gaps.length > 0 && ` · 관측 공백 ${p.gaps.length}구간`}
            </span>
            <span>{formatTime(end)}</span>
          </div>
        </div>
      )}
    </div>
  )
}
