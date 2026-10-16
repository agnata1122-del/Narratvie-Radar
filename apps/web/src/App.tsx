import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react'
import { api, type ChangeItem, type Frames } from './api'
import ChangesPanel from './components/ChangesPanel'
import type { Highlight, Selection } from './components/GraphView'
import Header from './components/Header'
import Inspector from './components/Inspector'
import Legend from './components/Legend'
import Timeline, { type RangeDays } from './components/Timeline'
import { Muted, Panel } from './components/ui'
import { changeKey, type ChangeWindow } from './lib/changes'
import { nodeIdsByLabel } from './lib/frames'
import { computeLayout } from './lib/layout'
import { addHours, defaultRange, formatTime } from './lib/time'

// 범위별 프레임 수: 3일 1시간, 7일 2시간, 14일 4시간, 30일 8시간 간격
const STEPS: Record<RangeDays, number> = { 3: 73, 7: 85, 14: 85, 30: 91 }
const PLAY_INTERVAL_MS = 900

// 그래프 렌더러(sigma·WebGL)는 따로 받아 첫 화면을 가볍게 한다
const GraphView = lazy(() => import('./components/GraphView'))

const once = { staleTime: Infinity, refetchOnWindowFocus: false, retry: false } as const

function Toggle({ checked, onChange, children }: { checked: boolean; onChange: (v: boolean) => void; children: string }) {
  return (
    <label className="flex cursor-pointer items-center gap-1 text-[11px] whitespace-nowrap text-nr-muted">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="accent-[var(--nr-accent)]" />
      {children}
    </label>
  )
}

export default function App() {
  const health = useQuery({ queryKey: ['health'], queryFn: ({ signal }) => api.health(signal) })
  const overview = useQuery({ queryKey: ['overview'], queryFn: ({ signal }) => api.overview(signal), ...once })
  // 방문 기록은 한 번만 남긴다 (StrictMode 두 번 마운트에도 요청 하나)
  const visit = useQuery({ queryKey: ['visit'], queryFn: () => api.visit(), ...once, gcTime: Infinity })

  const [rangeDays, setRangeDays] = useState<RangeDays>(14)
  const range = useMemo(
    () => (overview.data ? defaultRange(overview.data.time.start, overview.data.time.now, rangeDays) : null),
    [overview.data, rangeDays],
  )
  const hasGraph = (overview.data?.counts.nodes ?? 0) > 0
  const frames = useQuery({
    queryKey: ['frames', range?.start, range?.end, STEPS[rangeDays]],
    queryFn: ({ signal }) => api.frames(range!.start, range!.end, STEPS[rangeDays], signal),
    enabled: range !== null && hasGraph,
    placeholderData: keepPreviousData,
    ...once,
  })
  const events = useQuery({
    queryKey: ['events', range?.start, range?.end],
    queryFn: ({ signal }) => api.events(range!.start, range!.end, signal),
    enabled: range !== null && hasGraph,
    ...once,
  })
  const gaps = useQuery({
    queryKey: ['gaps', range?.start, range?.end],
    queryFn: ({ signal }) => api.gaps(range!.start, range!.end, signal),
    enabled: range !== null,
    ...once,
  })

  // 재생 위치는 어떤 프레임 묶음에 대한 것인지와 함께 둔다. 범위가 바뀌면 최신 시점으로 돌아간다.
  const [cursor, setCursor] = useState<{ frames: Frames; i: number } | null>(null)
  const f = frames.data
  const last = f ? f.frames.length - 1 : 0
  const index = f && cursor?.frames === f ? cursor.i : last
  const setIndex = useCallback((i: number) => f && setCursor({ frames: f, i }), [f])
  const asOf = f?.frames[index]?.t ?? overview.data?.time.now ?? null

  // 마지막 프레임에 닿으면 재생은 저절로 멈춘 것으로 본다
  const [playRequested, setPlaying] = useState(false)
  const playing = playRequested && index < last
  const [speed, setSpeed] = useState(1)
  useEffect(() => {
    if (!playing || !f) return
    const timer = setTimeout(() => setCursor({ frames: f, i: index + 1 }), PLAY_INTERVAL_MS / speed)
    return () => clearTimeout(timer)
  }, [playing, f, index, speed])
  const togglePlay = () => {
    if (!playing && index >= last) setIndex(0)
    setPlaying(!playing)
  }

  const rootId = overview.data?.profile.root_node_id ?? null
  const positions = useMemo(() => (f ? computeLayout(f, rootId) : {}), [f, rootId])
  const labelToId = useMemo(() => nodeIdsByLabel(f), [f])

  const [selection, setSelection] = useState<Selection>(null)
  const [highlight, setHighlight] = useState<Highlight>(null)
  const [activeChange, setActiveChange] = useState<string | null>(null)
  const [showCoMention, setShowCoMention] = useState(false)
  const [showPending, setShowPending] = useState(true)

  const select = useCallback((s: Selection) => {
    setSelection(s)
    setHighlight(null)
    setActiveChange(null)
  }, [])
  const pickChange = (item: ChangeItem) => {
    const key = changeKey(item)
    if (activeChange === key) {
      select(null)
      return
    }
    setActiveChange(key)
    setHighlight({ nodeIds: item.node_ids, edgeId: item.edge_id })
    setSelection(item.edge_id ? { kind: 'edge', id: item.edge_id } : item.node_ids[0] ? { kind: 'node', id: item.node_ids[0] } : null)
  }

  // "달라진 점" 기간: 재생 시점까지. 지난 방문이 그보다 뒤면 최근 24시간으로 본다.
  const previousSeenAt = visit.data?.previous_seen_at ?? null
  const [changeWindow, setChangeWindow] = useState<ChangeWindow | null>(null)
  const win: ChangeWindow = changeWindow ?? (previousSeenAt ? 'visit' : '24h')
  const since = useMemo(() => {
    if (!asOf) return null
    if (win === 'visit' && previousSeenAt && new Date(previousSeenAt) < new Date(asOf)) return previousSeenAt
    return addHours(asOf, win === '7d' ? -24 * 7 : -24)
  }, [asOf, win, previousSeenAt])
  const changes = useQuery({
    queryKey: ['changes', since, asOf],
    queryFn: ({ signal }) => api.changes(since!, asOf!, signal),
    enabled: since !== null && asOf !== null && hasGraph,
    placeholderData: keepPreviousData,
    ...once,
  })

  const noData = overview.isSuccess && !hasGraph
  const uninitialized = health.data?.database === 'uninitialized'

  return (
    <div className="flex min-h-full flex-col md:h-full">
      <Header overview={overview.data} health={health.data} healthPending={health.isPending} healthError={health.isError} />

      <main className="grid flex-1 grid-cols-1 gap-px bg-nr-border md:min-h-0 md:grid-cols-[280px_1fr_360px]">
        <Panel title="달라진 점">
          {hasGraph ? (
            <ChangesPanel
              report={changes.data}
              loading={changes.isPending && changes.fetchStatus !== 'idle'}
              error={changes.isError}
              window={win}
              hasVisit={previousSeenAt !== null}
              onWindow={setChangeWindow}
              activeKey={activeChange}
              onPick={pickChange}
            />
          ) : (
            <div className="p-3">
              <Muted>그래프가 생기면 지난 방문 이후 새로 관측된 것, 달라진 기존 이야기, 그 근거가 여기에 표시된다.</Muted>
            </div>
          )}
        </Panel>

        <Panel
          title="선택한 커뮤니티에서 관측된 내러티브"
          className="order-first md:order-none"
          actions={
            hasGraph && (
              <>
                <Toggle checked={showPending} onChange={setShowPending}>
                  검토 대기 보기
                </Toggle>
                <Toggle checked={showCoMention} onChange={setShowCoMention}>
                  함께 언급 선
                </Toggle>
              </>
            )
          }
        >
          <div className="relative h-[60vh] md:h-full">
            {f && Object.keys(f.nodes).length > 0 ? (
              <Suspense fallback={<div className="p-3"><Muted>그래프 준비 중…</Muted></div>}>
                <GraphView
                  frames={f}
                  frameIndex={index}
                  positions={positions}
                  rootId={rootId}
                  selection={selection}
                  highlight={highlight}
                  showCoMention={showCoMention}
                  showPending={showPending}
                  onSelect={select}
                />
                <Legend />
              </Suspense>
            ) : (
              <div className="flex h-full items-center justify-center p-6">
                <div className="max-w-sm space-y-2 text-center">
                  {(overview.isPending || frames.isFetching) && <Muted>불러오는 중…</Muted>}
                  {(overview.isError || uninitialized) && (
                    <Muted>
                      {uninitialized ? '데이터베이스가 아직 만들어지지 않았다. nr db upgrade 를 먼저 실행한다.' : '데이터를 불러오지 못했다. API 서버를 확인한다.'}
                    </Muted>
                  )}
                  {(noData || (f && Object.keys(f.nodes).length === 0)) && (
                    <>
                      <p className="text-sm font-medium text-nr-text">아직 그려질 그래프가 없다</p>
                      <Muted>
                        수집 → 분류 → 그래프 생성이 한 번 이상 돌아야 한다. 수집이 꺼져 있으면 위 소스 상태를 확인한다. 실행 순서는 docs/OPERATIONS.md 에 있다.
                      </Muted>
                      {overview.data && <Muted>지금까지 수집한 글 {overview.data.counts.documents}건</Muted>}
                    </>
                  )}
                </div>
              </div>
            )}
          </div>
        </Panel>

        <Panel title={asOf ? `위키 · 근거 (${formatTime(asOf)} 기준)` : '위키 · 근거'}>
          {asOf && <Inspector selection={selection} asOf={asOf} frames={f} frameIndex={index} labelToId={labelToId} onSelect={select} />}
        </Panel>
      </main>

      {f && f.frames.length > 1 && (
        <Timeline
          times={f.frames.map((x) => x.t)}
          index={index}
          onIndex={(i) => {
            setPlaying(false)
            setIndex(i)
          }}
          playing={playing}
          onTogglePlay={togglePlay}
          speed={speed}
          onSpeed={setSpeed}
          rangeDays={rangeDays}
          onRangeDays={(d) => {
            setPlaying(false)
            setRangeDays(d)
          }}
          events={events.data ?? []}
          gaps={gaps.data ?? []}
          previousSeenAt={previousSeenAt}
        />
      )}

      <footer className="border-t border-nr-border bg-nr-surface px-4 py-1.5 text-[11px] text-nr-muted">
        선택한 커뮤니티에서 관측된 주장을 정리한 것이다. 사실 확인을 거치지 않았고 투자 조언이 아니다.
      </footer>
    </div>
  )
}
