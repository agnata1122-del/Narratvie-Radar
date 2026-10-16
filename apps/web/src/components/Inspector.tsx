import { useQuery } from '@tanstack/react-query'
import { api, type Frames, type WikiSection } from '../api'
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
import { safeHref } from '../lib/url'
import { formatTime } from '../lib/time'
import type { Selection } from './GraphView'
import { Chip, Muted } from './ui'

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

function Section({ section, onLink, isKnown }: { section: WikiSection; onLink: (label: string) => void; isKnown: (label: string) => boolean }) {
  return (
    <section className="border-t border-nr-border px-3 py-2.5" data-section={section.key}>
      <h3 className="mb-1.5 text-xs font-semibold text-nr-muted">{section.title}</h3>
      <div className="text-sm leading-6 text-nr-text">
        <Markdown source={section.markdown} onNodeLink={onLink} isKnownNode={isKnown} />
      </div>
    </section>
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
      <div className="p-3">
        <h2 className="text-base font-semibold">{meta?.label ?? id}</h2>
        <Muted>{notKnownYet(q.error) ? '이 시점에는 아직 관측되지 않았다. 재생 시점을 뒤로 옮겨 보라.' : '정보를 불러오지 못했다.'}</Muted>
      </div>
    )
  }
  if (!q.data) return <div className="p-3"><Muted>불러오는 중…</Muted></div>

  const { node, wiki, narrative } = q.data
  const links = new Map<string, string>()
  for (const s of wiki?.sections ?? []) for (const l of s.links) links.set(l.label, l.node_id)
  const resolve = (name: string) => links.get(name) ?? labelToId.get(name)
  const onLink = (name: string) => {
    const target = resolve(name)
    if (target) onSelect({ kind: 'node', id: target })
  }

  return (
    <div>
      <div className="space-y-1.5 p-3">
        <h2 className="text-base font-semibold text-nr-text">{node?.label ?? meta?.label ?? id}</h2>
        <div className="flex flex-wrap gap-1">
          <Chip>{label(NODE_TYPE_LABEL, node?.node_type ?? meta?.type)}</Chip>
          {node && <Chip>{label(NODE_STATUS_LABEL, node.status)}</Chip>}
          {node && <Chip tone={node.membership === 'pending_review' ? 'warn' : 'plain'}>{label(MEMBERSHIP_LABEL, node.membership)}</Chip>}
          {!present && <Chip tone="warn">현재 필터·시점에서 숨김</Chip>}
        </div>
        {node && (
          <Muted>
            최근 7일 언급 {node.mentions_7d}건 · 독립 근거 {node.independent_7d}
          </Muted>
        )}
        {narrative && (
          <div className="rounded border border-nr-border px-2 py-1.5 text-sm">
            <div className="text-xs text-nr-muted">명제</div>
            <div className="text-nr-text">{narrative.proposition}</div>
            {narrative.state && <div className="mt-0.5 text-xs text-nr-muted">상태: {label(NARRATIVE_STATE_LABEL, narrative.state)}</div>}
          </div>
        )}
        {wiki ? (
          <Muted>
            위키 v{wiki.version} · {formatTime(wiki.available_at)} 기준 · 수집 기록에서 자동 정리 ({wiki.generator})
          </Muted>
        ) : (
          <Muted>이 시점에는 아직 위키가 없다.</Muted>
        )}
      </div>
      {wiki?.sections.map((s) => (
        <Section key={s.key} section={s} onLink={onLink} isKnown={(name) => resolve(name) !== undefined} />
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
      <div className="p-3">
        <Muted>{notKnownYet(q.error) ? '이 시점에는 아직 관측되지 않은 연결이다.' : '정보를 불러오지 못했다.'}</Muted>
      </div>
    )
  }
  if (!q.data) return <div className="p-3"><Muted>불러오는 중…</Muted></div>
  const e = q.data

  return (
    <div>
      <div className="space-y-1.5 p-3">
        <h2 className="flex flex-wrap items-center gap-1 text-base font-semibold text-nr-text">
          <button type="button" className="hover:text-nr-accent" onClick={() => onSelect({ kind: 'node', id: e.source.node_id })}>
            {e.source.label}
          </button>
          <span className="text-nr-muted">→</span>
          <button type="button" className="hover:text-nr-accent" onClick={() => onSelect({ kind: 'node', id: e.target.node_id })}>
            {e.target.label}
          </button>
        </h2>
        <div className="flex flex-wrap gap-1">
          <Chip>{label(RELATION_LABEL, e.relation)}</Chip>
          {value && <Chip tone={value[1] === 'confirmed' ? 'accent' : 'plain'}>{label(EDGE_STATUS_LABEL, value[1])}</Chip>}
        </div>
        {value && (
          <Muted>
            강도 {value[0].toFixed(2)} · 독립 근거 {value[2]} · 근거 글 {e.evidence.length}건
          </Muted>
        )}
        <Muted>독립 근거는 서로 베낀 글 묶음과 같은 작성자를 하나로 센 수다. 주장 내용이 사실인지는 확인하지 않았다.</Muted>
      </div>
      <section className="border-t border-nr-border px-3 py-2.5">
        <h3 className="mb-1.5 text-xs font-semibold text-nr-muted">근거</h3>
        {e.evidence.length === 0 && <Muted>이 시점까지 기록된 근거가 없다.</Muted>}
        <ul className="space-y-2">
          {e.evidence.map((ev) => {
            const href = ev.url ? safeHref(ev.url) : null
            return (
              <li key={ev.document_id} className="text-sm">
                <div className="text-xs text-nr-muted">
                  {label(SOURCE_LABEL, ev.source)} · {formatTime(ev.published_at)}
                  {ev.evidence_status && <> · {label(EVIDENCE_STATUS_LABEL, ev.evidence_status)}</>}
                </div>
                {ev.deleted ? (
                  <div className="text-xs text-nr-muted italic">작성자가 지운 글이라 내용과 링크를 보여주지 않는다.</div>
                ) : (
                  <>
                    {ev.excerpt && <div className="text-nr-text">“{ev.excerpt}”</div>}
                    {href && (
                      <a href={href} target="_blank" rel="noopener noreferrer nofollow" className="text-xs text-nr-accent hover:underline">
                        원문 보기
                      </a>
                    )}
                  </>
                )}
              </li>
            )
          })}
        </ul>
      </section>
    </div>
  )
}

export default function Inspector(props: Props) {
  const { selection } = props
  if (!selection) {
    return (
      <div className="space-y-2 p-3">
        <Muted>그래프에서 노드를 누르면 위키가, 선을 누르면 그 연결의 근거 글이 열린다.</Muted>
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
