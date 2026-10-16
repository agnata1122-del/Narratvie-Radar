import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { api, type Frames, type WikiSection } from '../api'
import { TYPE_GROUP } from '../lib/graphStyle'
import {
  EDGE_STATUS_LABEL,
  EVIDENCE_STATUS_LABEL,
  MEMBERSHIP_LABEL,
  NARRATIVE_STATE_LABEL,
  NODE_STATUS_LABEL,
  NODE_TYPE_LABEL,
  RELATION_LABEL,
  SOURCE_LABEL,
  label,
} from '../lib/labels'
import { Markdown } from '../lib/markdown'
import { formatTime } from '../lib/time'
import { safeHref } from '../lib/url'
import type { Selection } from './GraphView'
import { LinkOutIcon } from './icons'
import { Chip, Muted, Skeleton } from './ui'

type Props = {
  selection: Selection
  asOf: string
  frames: Frames | undefined
  frameIndex: number
  labelToId: Map<string, string>
  onSelect: (selection: Selection) => void
}

function notKnownYet(error: unknown): boolean {
  return error instanceof Error && error.message.endsWith(': 404')
}

function Swatch({ type }: { type: string | undefined }) {
  const group = TYPE_GROUP[type ?? ''] ?? 'concept'
  return (
    <span
      className={`inline-block size-2.5 shrink-0 ${group === 'narrative' ? 'scale-90 rotate-45 rounded-[2px]' : 'rounded-full'}`}
      style={{ background: `var(--nr-series-${group})` }}
      aria-hidden="true"
    />
  )
}

function Stat({ value, children }: { value: ReactNode; children: string }) {
  return (
    <div className="rounded-lg bg-nr-surface-2 px-2.5 py-2 ring-1 ring-nr-border ring-inset">
      <div className="text-base leading-5 font-semibold text-nr-text">{value}</div>
      <div className="mt-0.5 text-[11px] text-nr-muted">{children}</div>
    </div>
  )
}

/** 지지(파랑) ↔ 반박(빨강) 두 갈래 막대. 숫자를 함께 적어 색만으로 읽지 않게 한다. */
function StanceBar({ supports, contradicts }: { supports: number; contradicts: number }) {
  const total = supports + contradicts
  const s = total ? supports / total : 0.5
  return (
    <div>
      <div className="flex h-1.5 gap-[2px] overflow-hidden rounded-full" aria-hidden="true">
        {total === 0 ? (
          <div className="flex-1 bg-nr-border-strong" />
        ) : (
          <>
            {supports > 0 && <div className="rounded-l-full bg-nr-support transition-[flex-grow] duration-[var(--nr-dur-4)] ease-nr-out" style={{ flexGrow: s }} />}
            {contradicts > 0 && <div className="rounded-r-full bg-nr-contradict transition-[flex-grow] duration-[var(--nr-dur-4)] ease-nr-out" style={{ flexGrow: 1 - s }} />}
          </>
        )}
      </div>
      <div className="mt-1 flex justify-between text-[11px] text-nr-muted tabular-nums">
        <span>
          지지 <span className="font-semibold text-nr-text">{supports}</span>
        </span>
        <span>
          반박 <span className="font-semibold text-nr-text">{contradicts}</span>
        </span>
      </div>
    </div>
  )
}

function Section({ section, onLink, isKnown, order }: { section: WikiSection; onLink: (label: string) => void; isKnown: (label: string) => boolean; order: number }) {
  return (
    <section className="nr-rise border-t border-nr-border px-4 py-3" data-section={section.key} style={{ animationDelay: `${order * 35}ms` }}>
      <h3 className="mb-1.5 text-[11px] font-semibold tracking-wide text-nr-muted">{section.title}</h3>
      <div className="text-[13px] leading-6 text-nr-text">
        <Markdown source={section.markdown} onNodeLink={onLink} isKnownNode={isKnown} />
      </div>
    </section>
  )
}

function Loading() {
  return (
    <div className="space-y-3 p-4" aria-busy="true">
      <Skeleton className="h-4 w-24" />
      <Skeleton className="h-6 w-48" />
      <div className="grid grid-cols-3 gap-2">
        <Skeleton className="h-14" />
        <Skeleton className="h-14" />
        <Skeleton className="h-14" />
      </div>
      <Skeleton className="h-24" />
    </div>
  )
}

function NodeInspector({ id, asOf, frames, frameIndex, labelToId, onSelect }: Omit<Props, 'selection'> & { id: string }) {
  const q = useQuery({
    queryKey: ['node', id, asOf],
    queryFn: ({ signal }) => api.node(id, asOf, signal),
    retry: false,
    placeholderData: (prev, prevQuery) => (prevQuery?.queryKey[1] === id ? prev : undefined),
  })
  const meta = frames?.nodes[id]
  const present = frames?.frames[frameIndex]?.nodes[id] !== undefined

  if (q.isError) {
    return (
      <div className="nr-fade space-y-1 p-4">
        <div className="flex items-center gap-1.5 text-[11px] text-nr-muted">
          <Swatch type={meta?.type} />
          {label(NODE_TYPE_LABEL, meta?.type)}
        </div>
        <h2 className="text-lg font-semibold text-nr-text">{meta?.label ?? id}</h2>
        <Muted>{notKnownYet(q.error) ? '이 시점에는 아직 관측되지 않았다. 재생 시점을 뒤로 옮겨 보라.' : '정보를 불러오지 못했다.'}</Muted>
      </div>
    )
  }
  if (!q.data) return <Loading />

  const { node, wiki, narrative } = q.data
  const links = new Map<string, string>()
  for (const s of wiki?.sections ?? []) for (const l of s.links) links.set(l.label, l.node_id)
  const resolve = (name: string) => links.get(name) ?? labelToId.get(name)
  const onLink = (name: string) => {
    const target = resolve(name)
    if (target) onSelect({ kind: 'node', id: target })
  }
  const type = node?.node_type ?? meta?.type

  return (
    <div className="nr-fade">
      <div className="space-y-3 p-4">
        <div>
          <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-nr-muted">
            <Swatch type={type} />
            <span className="font-medium text-nr-text-2">{label(NODE_TYPE_LABEL, type)}</span>
            {node && <Chip tone="quiet">{label(NODE_STATUS_LABEL, node.status)}</Chip>}
            {node && <Chip tone={node.membership === 'pending_review' ? 'warn' : 'quiet'}>{label(MEMBERSHIP_LABEL, node.membership)}</Chip>}
            {!present && <Chip tone="warn">지금 필터·시점에서 숨김</Chip>}
          </div>
          <h2 className="mt-1 text-lg leading-6 font-semibold tracking-tight break-keep text-nr-text">{node?.label ?? meta?.label ?? id}</h2>
        </div>
        {node && (
          <div className="grid grid-cols-3 gap-2">
            <Stat value={node.mentions_7d}>최근 7일 언급</Stat>
            <Stat value={node.independent_7d}>독립 근거</Stat>
            <Stat value={`${(node.share_7d * 100).toFixed(1)}%`}>수집 글 중 비중</Stat>
          </div>
        )}
        {narrative && (
          <div className="space-y-2 rounded-xl bg-nr-surface-2 p-3 ring-1 ring-nr-border ring-inset">
            <div className="flex items-center gap-1.5 text-[11px] text-nr-muted">
              명제
              {narrative.state && <Chip tone="plain">{label(NARRATIVE_STATE_LABEL, narrative.state)}</Chip>}
            </div>
            <p className="text-sm leading-6 font-medium break-keep text-nr-text">{narrative.proposition}</p>
            <StanceBar supports={narrative.supports_recent} contradicts={narrative.contradicts_recent} />
          </div>
        )}
        {wiki ? (
          <p className="text-[11px] text-nr-muted">
            위키 v{wiki.version} · {formatTime(wiki.available_at)} 기준 · 수집 기록에서 자동 정리 ({wiki.generator})
          </p>
        ) : (
          <Muted>이 시점에는 아직 위키가 없다.</Muted>
        )}
      </div>
      {wiki?.sections.map((s, i) => (
        <Section key={s.key} section={s} onLink={onLink} isKnown={(name) => resolve(name) !== undefined} order={i} />
      ))}
    </div>
  )
}

function EdgeInspector({ id, asOf, frames, frameIndex, onSelect }: Omit<Props, 'selection' | 'labelToId'> & { id: string }) {
  const q = useQuery({
    queryKey: ['edge', id, asOf],
    queryFn: ({ signal }) => api.edge(id, asOf, signal),
    retry: false,
    placeholderData: (prev, prevQuery) => (prevQuery?.queryKey[1] === id ? prev : undefined),
  })
  const value = frames?.frames[frameIndex]?.edges[id]

  if (q.isError) {
    return (
      <div className="nr-fade p-4">
        <Muted>{notKnownYet(q.error) ? '이 시점에는 아직 관측되지 않은 연결이다.' : '정보를 불러오지 못했다.'}</Muted>
      </div>
    )
  }
  if (!q.data) return <Loading />
  const e = q.data
  const end = (n: { node_id: string; label: string }) => (
    <button
      type="button"
      className="inline-flex items-center gap-1.5 rounded-md text-left transition-colors hover:text-nr-link"
      onClick={() => onSelect({ kind: 'node', id: n.node_id })}
    >
      <Swatch type={frames?.nodes[n.node_id]?.type} />
      {n.label}
    </button>
  )

  return (
    <div className="nr-fade">
      <div className="space-y-3 p-4">
        <div>
          <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-nr-muted">
            <span className="font-medium text-nr-text-2">연결 · {label(RELATION_LABEL, e.relation)}</span>
            {value && <Chip tone={value[1] === 'confirmed' ? 'ink' : 'quiet'}>{label(EDGE_STATUS_LABEL, value[1])}</Chip>}
          </div>
          <h2 className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-lg leading-6 font-semibold tracking-tight text-nr-text">
            {end(e.source)}
            <span className="text-nr-muted" aria-label="에서">
              →
            </span>
            {end(e.target)}
          </h2>
        </div>
        {value && (
          <div className="grid grid-cols-3 gap-2">
            <Stat value={value[0].toFixed(2)}>강도</Stat>
            <Stat value={value[2]}>독립 근거</Stat>
            <Stat value={e.evidence.length}>근거 글</Stat>
          </div>
        )}
        <Muted>독립 근거는 서로 베낀 글 묶음과 같은 작성자를 하나로 센 수다. 주장 내용이 사실인지는 확인하지 않았다.</Muted>
      </div>
      <section className="border-t border-nr-border px-4 py-3">
        <h3 className="mb-2 text-[11px] font-semibold tracking-wide text-nr-muted">근거</h3>
        {e.evidence.length === 0 && <Muted>이 시점까지 기록된 근거가 없다.</Muted>}
        <ol className="relative space-y-3 border-l border-nr-border pl-4">
          {e.evidence.map((ev, i) => {
            const href = ev.url ? safeHref(ev.url) : null
            return (
              <li key={ev.document_id} className="nr-rise relative" style={{ animationDelay: `${Math.min(i * 40, 320)}ms` }}>
                <span className={`absolute top-1.5 -left-[19.5px] size-2 rounded-full ring-2 ring-nr-surface ${ev.deleted ? 'bg-nr-border-strong' : 'bg-nr-text-2'}`} />
                <div className="flex flex-wrap items-center gap-x-1.5 text-[11px] text-nr-muted">
                  <span className="font-medium text-nr-text-2">{label(SOURCE_LABEL, ev.source)}</span>
                  <span className="tabular-nums">{formatTime(ev.published_at)}</span>
                  {ev.evidence_status && <span>· {label(EVIDENCE_STATUS_LABEL, ev.evidence_status)}</span>}
                </div>
                {ev.deleted ? (
                  <p className="mt-0.5 text-xs text-nr-muted italic">작성자가 지운 글이라 내용과 링크를 보여주지 않는다.</p>
                ) : (
                  <>
                    {ev.excerpt && <p className="mt-0.5 text-[13px] leading-6 break-keep text-nr-text">“{ev.excerpt}”</p>}
                    {href && (
                      <a href={href} target="_blank" rel="noopener noreferrer nofollow" className="mt-0.5 inline-flex items-center gap-1 text-xs text-nr-link hover:underline">
                        원문 보기 <LinkOutIcon width={11} height={11} />
                      </a>
                    )}
                  </>
                )}
              </li>
            )
          })}
        </ol>
      </section>
    </div>
  )
}

export default function Inspector(props: Props) {
  const { selection } = props
  if (!selection) {
    return (
      <div className="nr-fade space-y-3 p-4">
        <div className="rounded-xl border border-dashed border-nr-border-strong p-4">
          <p className="text-sm font-medium text-nr-text">노드나 선을 눌러 보세요</p>
          <ul className="mt-2 space-y-1.5 text-xs leading-5 text-nr-text-2">
            <li>노드 → 위키: 개요, 관련 대상, 현재 내러티브, 상충하는 주장</li>
            <li>선 → 그 연결의 근거 글과 독립 근거 수</li>
            <li>왼쪽 항목 → 그래프에서 강조하고 카메라를 옮긴다</li>
          </ul>
        </div>
        <Muted>위키와 근거는 재생 시점 기준이다. 그 시점 이후에 알게 된 내용은 보이지 않는다.</Muted>
      </div>
    )
  }
  return selection.kind === 'node' ? (
    <NodeInspector key={selection.id} id={selection.id} {...props} />
  ) : (
    <EdgeInspector key={selection.id} id={selection.id} {...props} />
  )
}
