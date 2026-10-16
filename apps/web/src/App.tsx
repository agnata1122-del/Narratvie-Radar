import { useQuery } from '@tanstack/react-query'
import { fetchHealth, type SourceStatus } from './api'

const STATUS_LABEL: Record<SourceStatus['access_status'], string> = {
  not_authorized: '수집 꺼짐',
  test_mode: 'TEST MODE',
  live: 'LIVE',
  paused: '일시 중지',
  blocked: '차단 감지 · 중단됨',
  stopped: '오류 · 중단됨',
}

function Chip({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded border border-nr-border bg-nr-surface px-2 py-0.5 text-xs text-nr-text">
      {children}
    </span>
  )
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex min-h-0 flex-col border-nr-border bg-nr-surface">
      <h2 className="border-b border-nr-border px-3 py-2 text-xs font-semibold tracking-wide text-nr-muted uppercase">
        {title}
      </h2>
      <div className="min-h-0 flex-1 overflow-auto p-3 text-sm text-nr-muted">{children}</div>
    </section>
  )
}

export default function App() {
  const health = useQuery({ queryKey: ['health'], queryFn: ({ signal }) => fetchHealth(signal) })

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-2 border-b border-nr-border bg-nr-surface px-4 py-2">
        <h1 className="mr-2 text-base font-semibold">Narrative Radar</h1>
        <Chip>NVIDIA</Chip>
        <Chip>Depth 2</Chip>
        <Chip>Auto ON</Chip>
        <div className="ml-auto flex flex-wrap items-center gap-2 text-xs">
          {health.isPending && <span className="text-nr-muted">API 확인 중…</span>}
          {health.isError && <span className="text-nr-muted">API 연결 안 됨</span>}
          {health.data?.sources.map((s) => (
            <span
              key={s.id}
              className="rounded bg-nr-warn-bg px-2 py-0.5 text-nr-warn-text"
              title={s.id}
            >
              {s.display_name} · {STATUS_LABEL[s.access_status]}
            </span>
          ))}
        </div>
      </header>

      <main className="grid min-h-0 flex-1 grid-cols-1 gap-px bg-nr-border md:grid-cols-[220px_1fr_320px]">
        <Panel title="달라진 점 · 필터">
          지난 방문 이후 새로 관측된 것, 달라진 기존 이야기, 그 근거가 여기에 표시됩니다.
        </Panel>
        <Panel title="Knowledge Graph">선택한 커뮤니티에서 관측된 내러티브 그래프 (M8)</Panel>
        <Panel title="Wiki Inspector">노드를 선택하면 위키와 근거가 표시됩니다 (M6).</Panel>
      </main>

      <footer className="border-t border-nr-border bg-nr-surface px-4 py-2 text-xs text-nr-muted">
        <div>타임라인 · 재생 (M9)</div>
        <p className="mt-1">
          이 화면은 커뮤니티에서 관측된 주장을 보여줄 뿐이며 투자 조언이 아닙니다.
        </p>
      </footer>
    </div>
  )
}
