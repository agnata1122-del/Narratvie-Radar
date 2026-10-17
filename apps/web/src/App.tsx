import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, api, type ChangeItem, type Frames } from './api'
import ChangesPanel from './components/ChangesPanel'
import EmptyRadar from './components/EmptyRadar'
import type { Highlight, Selection } from './components/GraphView'
import Header from './components/Header'
import Inspector from './components/Inspector'
import Legend from './components/Legend'
import { MarketStrip } from './components/MarketStrip'
import Timeline, { type RangeDays } from './components/Timeline'
import { SparkIcon } from './components/icons'
import { Muted, Panel, Skeleton, Switch } from './components/ui'
import { changeKey, type ChangeWindow } from './lib/changes'
import { nodeIdsByLabel } from './lib/frames'
import { computeLayout } from './lib/layout'
import { useTheme } from './lib/theme'
import { addHours, defaultRange, formatTime } from './lib/time'

// 범위별 프레임 수: 3일 1시간, 7일 2시간, 14일 4시간, 30일 8시간 간격
const STEPS: Record<RangeDays, number> = { 3: 73, 7: 85, 14: 85, 30: 91 }
const PLAY_INTERVAL_MS = 900
const PIVOT_DIVE_MS = 480

// 그래프 렌더러(sigma·WebGL)는 따로 받아 첫 화면을 가볍게 한다
const GraphView = lazy(() => import('./components/GraphView'))

const once = { staleTime: Infinity, refetchOnWindowFocus: false, retry: false } as const

/** 지금 보는 관심사(가지)는 주소의 ?p= 에 둔다. 새로고침·공유·뒤로 가기에 그대로 남는다. */
function readProfileParam(): string | null {
  try {
    return new URLSearchParams(window.location.search).get('p')
  } catch {
    return null
  }
}

function pivotErrorText(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 401) return '방문 기록을 만든 뒤 다시 시도해 주세요.'
    if (e.detail?.includes('levels deep')) return '가지 깊이 상한에 닿아 더 파고들 수 없다.'
    if (e.detail?.includes('interests')) return '관심사 수 상한에 닿아 새 가지를 만들 수 없다.'
  }
  return '파고들기를 하지 못했다.'
}

export default function App() {
  const theme = useTheme()
  const queryClient = useQueryClient()
  const [profileId, setProfileId] = useState<string | null>(readProfileParam)

  const health = useQuery({ queryKey: ['health'], queryFn: ({ signal }) => api.health(signal) })
  const overview = useQuery({
    queryKey: ['overview', profileId],
    queryFn: ({ signal }) => api.overview(profileId, signal),
    placeholderData: keepPreviousData,
    ...once,
  })
  // 방문 기록은 한 번만 남긴다 (StrictMode 두 번 마운트에도 요청 하나)
  const visit = useQuery({ queryKey: ['visit'], queryFn: () => api.visit(), ...once, gcTime: Infinity })

  const [rangeDays, setRangeDays] = useState<RangeDays>(14)
  const range = useMemo(
    () => (overview.data ? defaultRange(overview.data.time.start, overview.data.time.now, rangeDays) : null),
    [overview.data, rangeDays],
  )
  const hasGraph = (overview.data?.counts.nodes ?? 0) > 0
  const frames = useQuery({
    queryKey: ['frames', profileId, range?.start, range?.end, STEPS[rangeDays]],
    queryFn: ({ signal }) => api.frames(profileId, range!.start, range!.end, STEPS[rangeDays], signal),
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
  // 트리 속 미국·한국 종목의 일봉 (D27). 시세를 받은 적이 없으면 빈 목록이라 화면이 그대로다
  const prices = useQuery({
    queryKey: ['prices', profileId, range?.start, range?.end],
    queryFn: ({ signal }) => api.prices(profileId, range!.start, range!.end, signal),
    enabled: range !== null && hasGraph,
    ...once,
  })

  // 재생 위치는 어떤 프레임 묶음에 대한 것인지와 함께 둔다. 범위·가지가 바뀌면 최신 시점으로 돌아간다.
  const [cursor, setCursor] = useState<{ frames: Frames; i: number } | null>(null)
  const f = frames.data
  const last = f ? f.frames.length - 1 : 0
  const index = f && cursor?.frames === f ? cursor.i : last
  const setIndex = useCallback((i: number) => f && setCursor({ frames: f, i }), [f])
  const asOf = f?.frames[index]?.t ?? overview.data?.time.now ?? null
  const reconstructed = !!f?.frames[index]?.reconstructed

  // 마지막 프레임에 닿으면 재생은 저절로 멈춘 것으로 본다
  const [playRequested, setPlaying] = useState(false)
  const playing = playRequested && index < last
  const [speed, setSpeed] = useState(1)
  useEffect(() => {
    if (!playing || !f) return
    const timer = setTimeout(() => setCursor({ frames: f, i: index + 1 }), PLAY_INTERVAL_MS / speed)
    return () => clearTimeout(timer)
  }, [playing, f, index, speed])
  const stepMs = PLAY_INTERVAL_MS / speed
  // 재생 중에는 한 칸 시간 안에 옮겨 가고, 손으로 옮길 때는 조금 더 여유 있게 움직인다
  const transitionMs = playing ? Math.min(800, Math.max(160, stepMs * 0.9)) : 560
  const togglePlay = () => {
    if (!playing && index >= last) setIndex(0)
    setPlaying(!playing)
  }

  const rootId = overview.data?.profile.root_node_id ?? null
  const layout = useMemo(() => (f ? computeLayout(f, rootId) : { positions: {}, rings: [] }), [f, rootId])
  const labelToId = useMemo(() => nodeIdsByLabel(f), [f])
  const times = useMemo(() => f?.frames.map((x) => x.t) ?? [], [f])
  // 타임라인 눈금은 이 트리에 나오는 노드·관계의 변화만
  const treeEvents = useMemo(
    () => (events.data ?? []).filter((e) => (e.node_id && f?.nodes[e.node_id]) || (e.edge_id && f?.edges[e.edge_id])),
    [events.data, f],
  )

  const [selection, setSelection] = useState<Selection>(null)
  const [highlight, setHighlight] = useState<Highlight>(null)
  const [activeChange, setActiveChange] = useState<string | null>(null)
  const [showCoMention, setShowCoMention] = useState(false)
  const [showPending, setShowPending] = useState(true)
  const [changesOpen, setChangesOpen] = useState(false)

  const select = useCallback((s: Selection) => {
    setSelection(s)
    setHighlight(null)
    setActiveChange(null)
  }, [])
  const presentIds = useMemo(() => new Set(Object.keys(f?.frames[index]?.nodes ?? {})), [f, index])
  const selectedNodeId = selection?.kind === 'node' ? selection.id : null
  const selectedPrice = prices.data?.series.find((s) => s.node_id === selectedNodeId) ?? null

  // 가지 이동: 선택·강조·재생 위치를 비우고 새 루트에서 다시 시작한다
  const openProfile = useCallback((id: string | null, push = true) => {
    setProfileId(id)
    setSelection(null)
    setHighlight(null)
    setActiveChange(null)
    setCursor(null)
    setPlaying(false)
    if (push) {
      try {
        const url = new URL(window.location.href)
        if (id) url.searchParams.set('p', id)
        else url.searchParams.delete('p')
        window.history.pushState({ p: id }, '', url)
      } catch {
        // 주소를 못 바꿔도 화면 전환은 된다
      }
    }
  }, [])
  useEffect(() => {
    const onPop = () => openProfile(readProfileParam(), false)
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [openProfile])

  // Focus Pivot: 카메라가 노드로 다가가는 동안 가지를 만들고, 다 되면 새 루트로 넘어간다
  const [focus, setFocus] = useState<{ nodeId: string; nonce: number } | null>(null)
  const [pivotError, setPivotError] = useState<string | null>(null)
  const [pivoting, setPivoting] = useState(false)
  const pivot = useCallback(
    async (nodeId: string) => {
      const parent = overview.data?.profile.profile_id
      if (!parent || nodeId === rootId || pivoting) return
      setPivotError(null)
      setPivoting(true)
      setFocus({ nodeId, nonce: Date.now() })
      const started = performance.now()
      try {
        const made = await api.branch(parent, nodeId)
        await queryClient.invalidateQueries({ queryKey: ['overview'] })
        const wait = Math.max(0, PIVOT_DIVE_MS - (performance.now() - started))
        window.setTimeout(() => {
          setFocus(null)
          setPivoting(false)
          openProfile(made.profile_id)
        }, wait)
      } catch (e) {
        setPivotError(pivotErrorText(e))
        setFocus(null)
        setPivoting(false)
      }
    },
    [overview.data, rootId, pivoting, queryClient, openProfile],
  )

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
    queryKey: ['changes', profileId, since, asOf],
    queryFn: ({ signal }) => api.changes(profileId, since!, asOf!, signal),
    enabled: since !== null && asOf !== null && hasGraph,
    placeholderData: keepPreviousData,
    ...once,
  })
  const changeCount = changes.data?.items.length ?? 0

  const noData = overview.isSuccess && !hasGraph
  const uninitialized = health.data?.database === 'uninitialized'
  const p = overview.data?.profile
  const bornAt = p && p.origin !== 'registered' ? p.created_at : null

  return (
    <div className="flex min-h-full flex-col lg:h-full">
      <Header
        overview={overview.data}
        health={health.data}
        healthPending={health.isPending}
        healthError={health.isError}
        theme={theme.mode}
        onTheme={theme.setMode}
        onOpenProfile={openProfile}
      />

      <main className="grid flex-1 grid-cols-1 gap-px bg-nr-border lg:min-h-0 lg:grid-cols-[minmax(0,1fr)_400px]">
        <Panel
          title="지식 트리"
          subtitle={p ? `${p.root_label} 중심 · 선택한 커뮤니티 기준` : undefined}
          actions={
            hasGraph && (
              <>
                <button
                  type="button"
                  onClick={() => setChangesOpen((v) => !v)}
                  aria-expanded={changesOpen}
                  className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium ring-1 transition-colors ring-inset ${
                    changesOpen ? 'bg-nr-text text-nr-surface ring-transparent' : 'bg-nr-surface text-nr-text-2 ring-nr-border hover:bg-nr-surface-2'
                  }`}
                >
                  <SparkIcon width={12} height={12} />
                  달라진 점
                  {changeCount > 0 && (
                    <span className={`rounded-full px-1.5 tabular-nums ${changesOpen ? 'bg-nr-surface/20' : 'bg-nr-text text-nr-surface'}`}>{changeCount}</span>
                  )}
                </button>
                <Switch checked={showPending} onChange={setShowPending}>
                  검토 대기
                </Switch>
                <Switch checked={showCoMention} onChange={setShowCoMention}>
                  함께 언급
                </Switch>
              </>
            )
          }
        >
          <div className="relative h-[64vh] lg:h-full">
            {f && Object.keys(f.nodes).length > 0 ? (
              <Suspense fallback={<Skeleton className="absolute inset-4" />}>
                <GraphView
                  frames={f}
                  frameIndex={index}
                  positions={layout.positions}
                  rings={layout.rings}
                  rootId={rootId}
                  selection={selection}
                  highlight={highlight}
                  showCoMention={showCoMention}
                  showPending={showPending}
                  onSelect={select}
                  onPivot={pivot}
                  focus={focus}
                  transitionMs={transitionMs}
                  theme={theme.resolved}
                />
                {/* 재생 시점 워터마크: 시점이 바뀔 때마다 살짝 페이드된다 */}
                {asOf && (
                  <div className="pointer-events-none absolute top-3 left-4 select-none" aria-hidden="true">
                    <div key={asOf} className="nr-fade text-[28px] leading-none font-semibold tracking-tight text-nr-text/10 tabular-nums">
                      {formatTime(asOf)}
                    </div>
                    <div className="mt-1 flex gap-2 text-[11px] font-medium text-nr-muted">
                      {playing && <span>재생 중 · {speed}×</span>}
                      {reconstructed && <span className="text-nr-warn-text">가지가 생기기 전 · 재구성</span>}
                    </div>
                  </div>
                )}
                {f.frames[index] && Object.keys(f.frames[index].nodes).length === 0 && (
                  <div className="pointer-events-none absolute inset-0 grid place-items-center">
                    <p className="nr-fade rounded-full bg-nr-surface/90 px-3 py-1.5 text-xs text-nr-muted shadow-nr">
                      이 시점에는 아직 {p?.root_label ?? '중심 노드'}이(가) 관측되지 않았다
                    </p>
                  </div>
                )}
                {changesOpen && (
                  <div className="nr-rise absolute top-3 bottom-3 left-3 z-10 flex w-[min(320px,calc(100%-1.5rem))] flex-col overflow-hidden rounded-xl border border-nr-border bg-nr-surface shadow-nr">
                    <div className="flex items-center justify-between border-b border-nr-border px-4 py-2">
                      <span className="text-[13px] font-semibold">달라진 점</span>
                      <button type="button" className="text-xs text-nr-muted hover:text-nr-text" onClick={() => setChangesOpen(false)}>
                        닫기
                      </button>
                    </div>
                    <div className="min-h-0 flex-1 overflow-auto">
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
                    </div>
                  </div>
                )}
                {pivotError && (
                  <div role="alert" className="nr-rise absolute top-3 left-1/2 z-20 -translate-x-1/2 rounded-full bg-nr-warn-bg px-3 py-1.5 text-xs font-medium text-nr-warn-text shadow-nr">
                    {pivotError}
                  </div>
                )}
                <Legend />
              </Suspense>
            ) : (
              <div className="nr-canvas-bg flex h-full items-center justify-center p-6">
                <div className="nr-fade flex max-w-sm flex-col items-center gap-3 text-center">
                  <EmptyRadar />
                  {(overview.isPending || frames.isFetching) && <Muted>불러오는 중…</Muted>}
                  {(overview.isError || uninitialized) && (
                    <Muted>
                      {uninitialized ? '데이터베이스가 아직 만들어지지 않았다. nr db upgrade 를 먼저 실행한다.' : '데이터를 불러오지 못했다. API 서버를 확인한다.'}
                    </Muted>
                  )}
                  {(noData || (f && Object.keys(f.nodes).length === 0)) && (
                    <>
                      <p className="text-sm font-semibold text-nr-text">아직 자라난 트리가 없다</p>
                      <Muted>
                        수집 → 분류 → 그래프 생성이 한 번 이상 돌아야 트리가 자라기 시작한다. 수집이 꺼져 있으면 오른쪽 위 수집 상태를 확인한다. 실행 순서는 docs/OPERATIONS.md 에 있다.
                      </Muted>
                      {overview.data && <Muted>지금까지 수집한 글 {overview.data.counts.documents}건</Muted>}
                    </>
                  )}
                </div>
              </div>
            )}
          </div>
        </Panel>

        <Panel title="위키 · 근거" subtitle={asOf ? `${formatTime(asOf)} 기준` : undefined}>
          {asOf && (
            <Inspector
              selection={selection}
              asOf={asOf}
              frames={f}
              frameIndex={index}
              labelToId={labelToId}
              onSelect={select}
              profileId={p?.profile_id ?? null}
              rootId={rootId}
              onPivot={pivot}
              pivoting={pivoting}
              onOpenProfile={openProfile}
              price={selectedPrice}
              range={range}
            />
          )}
        </Panel>
      </main>

      {range && asOf && prices.data && (
        <MarketStrip
          series={prices.data.series}
          asOf={asOf}
          start={range.start}
          end={range.end}
          presentIds={presentIds}
          selectedId={selectedNodeId}
          onSelect={(id) => select({ kind: 'node', id })}
        />
      )}

      {f && f.frames.length > 1 && (
        <Timeline
          times={times}
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
          events={treeEvents}
          gaps={gaps.data ?? []}
          previousSeenAt={previousSeenAt}
          stepMs={stepMs}
          bornAt={bornAt}
        />
      )}

      <footer className="border-t border-nr-border bg-nr-surface px-4 py-1.5 text-[11px] text-nr-muted">
        선택한 커뮤니티에서 관측된 주장을 정리한 것이다. 사실 확인을 거치지 않았고 투자 조언이 아니다.
      </footer>
    </div>
  )
}
