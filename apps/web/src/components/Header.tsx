import type { Health, Overview, SourceStatus } from '../api'
import { Chip } from './ui'

const STATUS_LABEL: Record<SourceStatus['access_status'], string> = {
  not_authorized: '수집 꺼짐',
  test_mode: 'TEST MODE',
  live: 'LIVE',
  paused: '일시 중지',
  blocked: '차단 감지 · 중단됨',
  stopped: '오류 · 중단됨',
}

type Props = {
  overview: Overview | undefined
  health: Health | undefined
  healthPending: boolean
  healthError: boolean
}

export default function Header({ overview, health, healthPending, healthError }: Props) {
  const p = overview?.profile
  return (
    <header className="flex flex-wrap items-center gap-2 border-b border-nr-border bg-nr-surface px-4 py-2">
      <h1 className="mr-2 text-base font-semibold">Narrative Radar</h1>
      <Chip tone="accent">{p?.root_label ?? p?.name ?? '관심 대상'}</Chip>
      {p && <Chip>Depth {p.max_depth}</Chip>}
      {p && <Chip>자동 확장 {p.auto_expand ? 'ON' : 'OFF'}</Chip>}
      {overview && (
        <span className="text-xs text-nr-muted">
          글 {overview.counts.documents.toLocaleString('ko-KR')} · 노드 {overview.counts.nodes} · 연결 {overview.counts.edges}
        </span>
      )}
      <div className="ml-auto flex flex-wrap items-center gap-1.5 text-xs">
        {healthPending && <span className="text-nr-muted">API 확인 중…</span>}
        {healthError && <span className="text-nr-muted">API 연결 안 됨</span>}
        {health?.sources.map((s) => (
          <span
            key={s.id}
            className={`rounded px-2 py-0.5 ${s.access_status === 'live' ? 'bg-nr-bg text-nr-text' : 'bg-nr-warn-bg text-nr-warn-text'}`}
            title={s.id}
          >
            {s.display_name} · {STATUS_LABEL[s.access_status]}
          </span>
        ))}
      </div>
    </header>
  )
}
