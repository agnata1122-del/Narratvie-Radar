import { useMemo, useState } from 'react'
import type { Gap, GraphEventRow } from '../api'
import { binEvents, positionIn } from '../lib/frames'
import { SOURCE_LABEL, label } from '../lib/labels'
import { formatTime } from '../lib/time'
import { PauseIcon, PlayIcon, StepBackIcon, StepForwardIcon } from './icons'
import { Segmented } from './ui'

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
  /** 재생 중 한 칸 넘어가는 시간. 재생 헤드가 이 시간 동안 미끄러진다. */
  stepMs: number
  /** 지금 보는 가지가 생긴 시각. 그 전 구간은 공통 그래프로 되살린 재구성이다 */
  bornAt?: string | null
}

const btn =
  'grid size-8 place-items-center rounded-lg text-nr-text-2 transition-colors duration-[var(--nr-dur-1)] hover:bg-nr-surface-2 hover:text-nr-text disabled:pointer-events-none disabled:opacity-35'

/** 가장자리에서는 툴팁을 안쪽으로 붙여 잘리지 않게 한다 */
function tooltipPosition(x: number): { left: string; transform: string } {
  const shift = x < 0.12 ? '0' : x > 0.88 ? '-100%' : '-50%'
  return { left: `${x * 100}%`, transform: `translateX(${shift})` }
}

export default function Timeline(p: TimelineProps) {
  const start = p.times[0]
  const end = p.times[p.times.length - 1]
  const last = p.times.length - 1
  const at = p.times[p.index]
  const bins = useMemo(() => binEvents(p.times, p.events), [p.times, p.events])
  const max = Math.max(1, ...bins.map((b) => b.total))
  const total = bins.reduce((n, b) => n + b.total, 0)
  const [hoverBin, setHoverBin] = useState<number | null>(null)
  const progress = last > 0 ? p.index / last : 1
  const hb = hoverBin !== null ? bins[hoverBin] : null

  return (
    <div className="sticky bottom-0 z-10 border-t border-nr-border bg-nr-surface/95 px-4 pt-2.5 pb-2 backdrop-blur lg:static">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <div className="flex items-center gap-1">
          <button type="button" className={btn} onClick={() => p.onIndex(Math.max(0, p.index - 1))} disabled={p.index === 0} aria-label="이전 시점">
            <StepBackIcon />
          </button>
          <button
            type="button"
            onClick={p.onTogglePlay}
            aria-label={p.playing ? '일시 정지' : '재생'}
            className="grid size-9 place-items-center rounded-full bg-nr-text text-nr-surface shadow-nr transition-transform duration-[var(--nr-dur-2)] ease-nr-spring hover:scale-105 active:scale-95"
          >
            <span key={p.playing ? 'pause' : 'play'} className="nr-fade">
              {p.playing ? <PauseIcon /> : <PlayIcon />}
            </span>
          </button>
          <button type="button" className={btn} onClick={() => p.onIndex(Math.min(last, p.index + 1))} disabled={p.index === last} aria-label="다음 시점">
            <StepForwardIcon />
          </button>
        </div>

        <div className="flex min-w-0 items-baseline gap-2" aria-live="polite">
          <span className="text-lg leading-none font-semibold tracking-tight text-nr-text tabular-nums">{at ? formatTime(at) : '—'}</span>
          {p.index === last ? (
            <span className="inline-flex items-center gap-1 text-[11px] font-medium text-nr-text-2">
              <span className="inline-block size-1.5 rounded-full bg-nr-text text-nr-text" style={{ animation: 'nr-live 2s ease-out infinite' }} />
              최신
            </span>
          ) : (
            <span className="text-[11px] text-nr-muted">재생 시점</span>
          )}
        </div>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          <Segmented label="재생 속도" value={p.speed} onChange={p.onSpeed} options={[1, 2, 4].map((s) => ({ value: s, text: `${s}×` }))} />
          <Segmented
            label="재생 범위"
            value={p.rangeDays}
            onChange={p.onRangeDays}
            options={([3, 7, 14, 30] as RangeDays[]).map((d) => ({ value: d, text: `${d}일` }))}
          />
        </div>
      </div>

      {start && end && (
        <div className="relative mt-2.5">
          {/* 구간별 변화 수 (막대) + 관측 공백 (빗금) + 지난 방문 + 재생 헤드 */}
          <div className="relative h-9" onMouseLeave={() => setHoverBin(null)}>
            {p.gaps.map((g, i) => {
              const a = positionIn(start, end, g.start)
              const b = positionIn(start, end, g.end)
              return (
                <div
                  key={`${g.source_adapter_id}-${i}`}
                  className="nr-hatch absolute inset-y-0 rounded-sm"
                  style={{ left: `${a * 100}%`, width: `${Math.max(0.5, (b - a) * 100)}%` }}
                  title={`${label(SOURCE_LABEL, g.source_adapter_id)} 관측 공백 · ${formatTime(g.start)} → ${formatTime(g.end)}`}
                />
              )
            })}
            <div className="absolute inset-0 flex items-end gap-[2px]" role="list" aria-label="구간별 그래프 변화 수">
              {bins.map((b, i) => {
                const played = i < p.index
                const h = b.total === 0 ? 0 : Math.max(3, (b.total / max) * 34)
                return (
                  <button
                    key={b.start}
                    type="button"
                    role="listitem"
                    aria-label={`${formatTime(b.start)}부터 변화 ${b.total}건`}
                    className="group relative flex h-full min-w-0 flex-1 items-end"
                    onMouseEnter={() => setHoverBin(i)}
                    onFocus={() => setHoverBin(i)}
                    onClick={() => p.onIndex(i + 1)}
                  >
                    <span
                      className={`block w-full origin-bottom rounded-t-[3px] transition-colors duration-[var(--nr-dur-3)] ${
                        hoverBin === i ? 'bg-nr-text' : played ? 'bg-nr-text-2/70' : 'bg-nr-border-strong'
                      }`}
                      style={{ height: h, animation: `nr-grow var(--nr-dur-4) var(--nr-ease-out) ${Math.min(i * 6, 360)}ms both` }}
                    />
                    {b.total === 0 && <span className="absolute bottom-0 h-px w-full bg-nr-border" />}
                  </button>
                )
              })}
            </div>
            {p.bornAt && new Date(p.bornAt) > new Date(start) && (
              <>
                <div
                  className="pointer-events-none absolute inset-y-0 left-0 rounded-sm bg-nr-surface-2/80"
                  style={{ width: `${positionIn(start, end, p.bornAt) * 100}%` }}
                  title="가지가 생기기 전: 공통 그래프로 되살린 재구성"
                />
                <div className="pointer-events-none absolute inset-y-0" style={{ left: `${positionIn(start, end, p.bornAt) * 100}%` }}>
                  <div className="h-full w-0.5 bg-nr-focus" />
                  <span
                    className={`absolute -top-0.5 rounded bg-nr-surface px-1 text-[10px] leading-3 font-semibold whitespace-nowrap text-nr-text ${
                      positionIn(start, end, p.bornAt) > 0.85 ? 'right-1' : 'left-1'
                    }`}
                  >
                    가지 생성
                  </span>
                </div>
              </>
            )}
            {p.previousSeenAt && new Date(p.previousSeenAt) > new Date(start) && (
              <div className="pointer-events-none absolute inset-y-0" style={{ left: `${positionIn(start, end, p.previousSeenAt) * 100}%` }}>
                <div className="h-full w-px bg-nr-text-2" />
                <span className="absolute -top-0.5 left-1 rounded bg-nr-surface px-1 text-[10px] leading-3 font-medium whitespace-nowrap text-nr-text-2">지난 방문</span>
              </div>
            )}
            <div
              className="pointer-events-none absolute inset-y-0 w-px bg-nr-focus"
              style={{
                left: `${progress * 100}%`,
                transition: `left ${p.playing ? p.stepMs : 260}ms ${p.playing ? 'linear' : 'var(--nr-ease-out)'}`,
              }}
            />
            {hb && hoverBin !== null && (
              <div
                className="nr-fade pointer-events-none absolute bottom-full z-20 mb-2 w-max max-w-60 rounded-lg border border-nr-border bg-nr-surface px-2.5 py-1.5 text-[11px] text-nr-text-2 shadow-nr"
                style={tooltipPosition((hoverBin + 0.5) / bins.length)}
                role="tooltip"
              >
                <div className="text-nr-muted tabular-nums">
                  {formatTime(hb.start)} – {formatTime(hb.end)}
                </div>
                <div className="font-semibold text-nr-text">변화 {hb.total}건</div>
                {hb.total > 0 && (
                  <div className="tabular-nums">
                    노드 {hb.nodes} · 연결 {hb.edges} · 내러티브 {hb.narratives}
                  </div>
                )}
              </div>
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
            className="nr-range mt-1"
            style={{ ['--nr-progress' as string]: `${progress * 100}%` }}
          />
          <div className="flex justify-between text-[11px] text-nr-muted tabular-nums">
            <span>{formatTime(start)}</span>
            <span>
              변화 {total}건{p.gaps.length > 0 && ` · 관측 공백 ${p.gaps.length}구간`}
            </span>
            <span>{formatTime(end)}</span>
          </div>
        </div>
      )}
    </div>
  )
}
