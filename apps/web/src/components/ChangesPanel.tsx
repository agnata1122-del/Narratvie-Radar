import type { ChangeItem, ChangeReport } from '../api'
import type { ChangeWindow } from '../lib/changes'
import { CAUSE_LABEL, CHANGE_KIND_LABEL, NARRATIVE_STATE_LABEL, RELATION_LABEL, SOURCE_LABEL, label } from '../lib/labels'
import { changeKey } from '../lib/changes'
import { safeHref } from '../lib/url'
import { formatTime } from '../lib/time'
import { Chip, Muted } from './ui'

const NEW_KINDS = new Set(['new_narrative', 'new_node', 'new_relation'])

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

function Item({ item, active, onPick }: { item: ChangeItem; active: boolean; onPick: (item: ChangeItem) => void }) {
  const detail = detailLine(item)
  const unusualCause = item.cause !== 'observed_new'
  return (
    <li>
      <button
        type="button"
        onClick={() => onPick(item)}
        aria-pressed={active}
        className={`w-full rounded border px-2 py-1.5 text-left transition-colors ${
          active ? 'border-nr-highlight bg-nr-bg' : 'border-nr-border hover:bg-nr-bg'
        }`}
      >
        <div className="flex flex-wrap items-center gap-1">
          <Chip tone={item.kind === 'attention_down' ? 'plain' : 'accent'}>{label(CHANGE_KIND_LABEL, item.kind)}</Chip>
          {unusualCause && (
            <Chip tone="warn" title="새로 관측된 변화가 아니라 시스템 쪽 변화">
              {label(CAUSE_LABEL, item.cause)}
            </Chip>
          )}
        </div>
        <div className="mt-1 text-sm font-medium text-nr-text">{item.label}</div>
        {detail && <div className="text-xs text-nr-muted">{detail}</div>}
        <div className="mt-0.5 text-[11px] text-nr-muted">
          확산 {item.spread_documents}건 · 독립 근거 {item.independent}
          {item.available_at && <> · {formatTime(item.available_at)}</>}
        </div>
      </button>
      {active && item.evidence.length > 0 && (
        <ul className="mt-1 space-y-1 border-l-2 border-nr-border pl-2">
          {item.evidence.slice(0, 4).map((ev) => {
            const href = safeHref(ev.url)
            return (
              <li key={ev.document_id} className="text-xs text-nr-muted">
                <span className="text-nr-text">{label(SOURCE_LABEL, ev.source)}</span> · {formatTime(ev.published_at)}
                {ev.excerpt && <span className="block text-nr-text">“{ev.excerpt}”</span>}
                {href && (
                  <a href={href} target="_blank" rel="noopener noreferrer nofollow" className="text-nr-accent hover:underline">
                    원문
                  </a>
                )}
              </li>
            )
          })}
        </ul>
      )}
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

export default function ChangesPanel({ report, loading, error, window, hasVisit, onWindow, activeKey, onPick }: ChangesPanelProps) {
  const fresh = report?.items.filter((i) => NEW_KINDS.has(i.kind)) ?? []
  const shifted = report?.items.filter((i) => !NEW_KINDS.has(i.kind)) ?? []
  const options: { value: ChangeWindow; text: string }[] = [
    ...(hasVisit ? [{ value: 'visit' as const, text: '지난 방문 이후' }] : []),
    { value: '24h', text: '최근 24시간' },
    { value: '7d', text: '최근 7일' },
  ]

  return (
    <div className="space-y-3 p-3">
      <div className="flex items-center gap-2">
        <label htmlFor="change-window" className="text-xs text-nr-muted">
          기간
        </label>
        <select
          id="change-window"
          value={window}
          onChange={(e) => onWindow(e.target.value as ChangeWindow)}
          className="rounded border border-nr-border bg-nr-surface px-1.5 py-0.5 text-xs text-nr-text"
        >
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.text}
            </option>
          ))}
        </select>
      </div>
      {report && (
        <Muted>
          {formatTime(report.since)} → {formatTime(report.until)}
        </Muted>
      )}
      {loading && <Muted>불러오는 중…</Muted>}
      {error && <Muted>달라진 점을 불러오지 못했다.</Muted>}
      {report && report.gaps.length > 0 && (
        <div className="rounded bg-nr-warn-bg px-2 py-1.5 text-xs text-nr-warn-text">
          이 기간에 관측 공백이 {report.gaps.length}구간 있다. 공백 때문에 생긴 감소는 신호에서 뺐다.
        </div>
      )}
      {report && report.items.length === 0 && <Muted>이 기간에 새로 관측되거나 달라진 것이 없다.</Muted>}
      {fresh.length > 0 && (
        <section>
          <h3 className="mb-1 text-xs font-semibold text-nr-text">새로 관측된 것</h3>
          <ul className="space-y-1.5">
            {fresh.map((item) => (
              <Item key={changeKey(item)} item={item} active={activeKey === changeKey(item)} onPick={onPick} />
            ))}
          </ul>
        </section>
      )}
      {shifted.length > 0 && (
        <section>
          <h3 className="mb-1 text-xs font-semibold text-nr-text">달라진 기존 이야기</h3>
          <ul className="space-y-1.5">
            {shifted.map((item) => (
              <Item key={changeKey(item)} item={item} active={activeKey === changeKey(item)} onPick={onPick} />
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
