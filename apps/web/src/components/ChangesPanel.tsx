import type { ComponentType, SVGProps } from 'react'
import type { ChangeItem, ChangeReport } from '../api'
import { changeKey, type ChangeWindow } from '../lib/changes'
import { CAUSE_LABEL, CHANGE_KIND_LABEL, NARRATIVE_STATE_LABEL, RELATION_LABEL, label, sourceName } from '../lib/labels'
import { formatTime, relativeTime } from '../lib/time'
import { safeHref } from '../lib/url'
import { LinkOutIcon, ShiftIcon, SparkIcon, TrendDownIcon, TrendUpIcon, WarnIcon } from './icons'
import { Chip, EvidenceMeter, Muted, Segmented, Skeleton } from './ui'

const NEW_KINDS = new Set(['new_narrative', 'new_node', 'new_relation'])

const KIND_ICON: Record<string, ComponentType<SVGProps<SVGSVGElement>>> = {
  new_narrative: SparkIcon,
  new_node: SparkIcon,
  new_relation: SparkIcon,
  narrative_shift: ShiftIcon,
  attention_up: TrendUpIcon,
  attention_down: TrendDownIcon,
}

function pct(v: unknown): string {
  return typeof v === 'number' ? `${(v * 100).toFixed(1)}%` : '?'
}

function detailLine(item: ChangeItem): string | null {
  const d = item.detail
  switch (item.kind) {
    case 'narrative_shift':
      return `${label(NARRATIVE_STATE_LABEL, d.from as string | null)} → ${label(NARRATIVE_STATE_LABEL, d.to as string | null)}`
    case 'new_narrative':
      return d.state ? `${label(NARRATIVE_STATE_LABEL, d.state as string)} · 지지 ${String(d.supports ?? 0)} / 반박 ${String(d.contradicts ?? 0)}` : null
    case 'new_relation':
      return label(RELATION_LABEL, d.relation as string)
    case 'attention_up':
    case 'attention_down':
      return `수집 글 중 비중 ${pct(d.share_before)} → ${pct(d.share_after)}`
    default:
      return null
  }
}

function Card({ item, active, onPick, until, order }: { item: ChangeItem; active: boolean; onPick: (item: ChangeItem) => void; until: string; order: number }) {
  const detail = detailLine(item)
  const Icon = KIND_ICON[item.kind] ?? SparkIcon
  return (
    <li className="nr-rise" style={{ animationDelay: `${Math.min(order * 45, 400)}ms` }}>
      <div
        className={`rounded-xl border transition-[background-color,border-color,box-shadow] duration-[var(--nr-dur-2)] ${
          active ? 'border-nr-focus/60 bg-nr-surface-2 shadow-nr' : 'border-nr-border hover:border-nr-border-strong hover:bg-nr-surface-2'
        }`}
      >
        <button type="button" onClick={() => onPick(item)} aria-pressed={active} className="flex w-full gap-2.5 px-3 py-2.5 text-left">
          <span
            className={`mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg transition-colors duration-[var(--nr-dur-2)] ${
              active ? 'bg-nr-text text-nr-surface' : 'bg-nr-surface-2 text-nr-text-2 ring-1 ring-nr-border ring-inset'
            }`}
          >
            <Icon width={14} height={14} />
          </span>
          <span className="min-w-0 flex-1">
            <span className="flex items-center gap-1.5 text-[11px] text-nr-muted">
              <span className="font-medium text-nr-text-2">{label(CHANGE_KIND_LABEL, item.kind)}</span>
              {item.cause !== 'observed_new' && (
                <Chip tone="warn" title="새로 관측된 변화가 아니라 시스템 쪽 변화">
                  {label(CAUSE_LABEL, item.cause)}
                </Chip>
              )}
              {item.available_at && (
                <span className="ml-auto shrink-0 tabular-nums" title={formatTime(item.available_at)}>
                  {relativeTime(item.available_at, until)}
                </span>
              )}
            </span>
            <span className="mt-0.5 block text-sm leading-5 font-semibold break-keep text-nr-text">{item.label}</span>
            {detail && <span className="block text-xs leading-5 text-nr-text-2">{detail}</span>}
            <span className="mt-1.5 block">
              <EvidenceMeter spread={item.spread_documents} independent={item.independent} />
            </span>
          </span>
        </button>
        <div className="nr-collapse" data-open={active && item.evidence.length > 0}>
          <div>
            {active && (
            <ul className="mx-3 mb-3 space-y-2 border-t border-nr-border pt-2.5">
              {item.evidence.slice(0, 4).map((ev) => {
                const href = safeHref(ev.url)
                return (
                  <li key={ev.document_id} className="text-xs">
                    <div className="flex items-center gap-1.5 text-[11px] text-nr-muted">
                      <span className="font-medium text-nr-text-2">{sourceName(ev.source, ev.url)}</span>
                      <span className="tabular-nums">{formatTime(ev.published_at)}</span>
                      {href && (
                        <a
                          href={href}
                          target="_blank"
                          rel="noopener noreferrer nofollow"
                          className="ml-auto inline-flex items-center gap-0.5 text-nr-link hover:underline"
                        >
                          원문 <LinkOutIcon width={11} height={11} />
                        </a>
                      )}
                    </div>
                    {ev.excerpt && <p className="mt-0.5 border-l-2 border-nr-border-strong pl-2 leading-5 text-nr-text">“{ev.excerpt}”</p>}
                  </li>
                )
              })}
            </ul>
            )}
          </div>
        </div>
      </div>
    </li>
  )
}

export type ChangesPanelProps = {
  report: ChangeReport | undefined
  loading: boolean
  error: boolean
  window: ChangeWindow
  hasVisit: boolean
  onWindow: (w: ChangeWindow) => void
  activeKey: string | null
  onPick: (item: ChangeItem) => void
}

function Group({ title, items, offset, activeKey, onPick, until }: { title: string; items: ChangeItem[]; offset: number; activeKey: string | null; onPick: (i: ChangeItem) => void; until: string }) {
  return (
    <section>
      <h3 className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold text-nr-text">
        {title}
        <span className="rounded-full bg-nr-surface-2 px-1.5 text-[10px] leading-4 font-medium text-nr-muted ring-1 ring-nr-border ring-inset tabular-nums">
          {items.length}
        </span>
      </h3>
      <ul className="space-y-2">
        {items.map((item, i) => (
          <Card key={changeKey(item)} item={item} active={activeKey === changeKey(item)} onPick={onPick} until={until} order={offset + i} />
        ))}
      </ul>
    </section>
  )
}

export default function ChangesPanel({ report, loading, error, window, hasVisit, onWindow, activeKey, onPick }: ChangesPanelProps) {
  const fresh = report?.items.filter((i) => NEW_KINDS.has(i.kind)) ?? []
  const shifted = report?.items.filter((i) => !NEW_KINDS.has(i.kind)) ?? []
  const options: { value: ChangeWindow; text: string }[] = [
    ...(hasVisit ? [{ value: 'visit' as const, text: '지난 방문' }] : []),
    { value: '24h', text: '24시간' },
    { value: '7d', text: '7일' },
  ]

  return (
    <div className="space-y-4 p-4">
      <div className="space-y-1.5">
        <Segmented label="달라진 점 기간" value={window} options={options} onChange={onWindow} />
        {report && (
          <p className="text-[11px] text-nr-muted tabular-nums">
            {formatTime(report.since)} → {formatTime(report.until)}
          </p>
        )}
      </div>
      {loading && !report && (
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-20" />
          ))}
        </div>
      )}
      {error && <Muted>달라진 점을 불러오지 못했다.</Muted>}
      {report && report.gaps.length > 0 && (
        <div className="flex gap-2 rounded-xl bg-nr-warn-bg px-3 py-2 text-xs leading-5 text-nr-warn-text">
          <WarnIcon className="mt-0.5 shrink-0" width={14} height={14} />
          <span>
            관측 공백 {report.gaps.length}구간이 있다. 공백 때문에 생긴 감소는 신호에서 뺐다.
          </span>
        </div>
      )}
      {report && report.items.length === 0 && (
        <div className="nr-fade rounded-xl border border-dashed border-nr-border-strong px-4 py-6 text-center">
          <p className="text-sm font-medium text-nr-text-2">조용한 구간</p>
          <Muted>이 기간에 새로 관측되거나 달라진 것이 없다.</Muted>
        </div>
      )}
      {report && fresh.length > 0 && <Group title="새로 관측된 것" items={fresh} offset={0} activeKey={activeKey} onPick={onPick} until={report.until} />}
      {report && shifted.length > 0 && (
        <Group title="달라진 기존 이야기" items={shifted} offset={fresh.length} activeKey={activeKey} onPick={onPick} until={report.until} />
      )}
    </div>
  )
}
