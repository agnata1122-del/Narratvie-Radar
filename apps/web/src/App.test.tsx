import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { GraphViewProps } from './components/GraphView'
import App from './App'
import * as fx from './test/fixtures'

// WebGL이 없는 jsdom에서는 그래프 대신 받은 값만 보여주는 가짜를 쓴다
vi.mock('./components/GraphView', () => ({
  default: (props: GraphViewProps) => (
    <div data-testid="graph" data-frame={props.frameIndex}>
      {Object.keys(props.frames.frames[props.frameIndex].nodes).length} nodes
      <button type="button" onClick={() => props.onSelect({ kind: 'edge', id: 'edg_2' })}>
        pick edge
      </button>
    </div>
  ),
}))

type Routes = { nodes?: number; failAll?: boolean }

function stubApi({ nodes = 3, failAll = false }: Routes = {}) {
  const calls: URL[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string, init?: RequestInit) => {
      const url = new URL(input, 'http://localhost')
      calls.push(url)
      if (failAll) return new Response('', { status: 502 })
      const path = url.pathname.replace(/^\/api/, '')
      const q = url.searchParams
      if (path === '/health') return Response.json(fx.health)
      if (path === '/overview') return Response.json(q.get('profile') === 'prf_hbm' ? fx.branchOverview() : fx.overview(nodes))
      if (path === '/profiles/branch' && init?.method === 'POST') return Response.json({ ...fx.BRANCH_SUMMARY, created: true })
      if (path === '/viewer/visit') return Response.json({ viewer_id: 'vwr_1', previous_seen_at: null })
      if (path === '/frames') return Response.json(fx.frames)
      if (path === '/events') return Response.json([{ t: fx.T1, type: 'NODE_CREATED', cause: 'observed_new', node_id: 'nod_hbm', edge_id: null }])
      if (path === '/gaps') return Response.json([])
      if (path === '/prices') return Response.json(fx.prices)
      if (path === '/changes') return Response.json(fx.changes(q.get('since')!, q.get('until')!))
      if (path.startsWith('/nodes/')) {
        const id = decodeURIComponent(path.slice('/nodes/'.length))
        if (id === 'nod_skh' && new Date(q.get('as_of')!) < new Date(fx.T2)) return new Response('', { status: 404 })
        return Response.json(fx.nodeDetail(id))
      }
      if (path.startsWith('/edges/')) return Response.json(fx.edgeDetail)
      return new Response('', { status: 404 })
    }),
  )
  return calls
}

async function openChanges() {
  fireEvent.click(await screen.findByRole('button', { name: /달라진 점/ }))
}

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('App', () => {
  it('shows each source status from the API instead of claiming live collection', async () => {
    stubApi()
    renderApp()
    expect(screen.getByRole('heading', { name: 'Narrative Radar' })).toBeInTheDocument()
    // 요약 알약은 "수집 꺼짐", 펼치면 소스별 상태
    expect(await screen.findByText('Hacker News · 수집 꺼짐')).toBeInTheDocument()
    expect(screen.getByText('수집 꺼짐')).toBeInTheDocument()
  })

  it('cycles the theme and remembers it on the page', async () => {
    stubApi()
    renderApp()
    fireEvent.click(screen.getByRole('button', { name: /시스템 테마/ }))
    expect(document.documentElement.dataset.theme).toBe('light')
    fireEvent.click(screen.getByRole('button', { name: /밝은 테마/ }))
    expect(document.documentElement.dataset.theme).toBe('dark')
    fireEvent.click(screen.getByRole('button', { name: /어두운 테마/ }))
    expect(document.documentElement.dataset.theme).toBeUndefined()
  })

  it('shows a disconnected state when the API is unreachable', async () => {
    stubApi({ failAll: true })
    renderApp()
    expect(await screen.findByText('API 연결 안 됨')).toBeInTheDocument()
  })

  it('explains the empty state instead of drawing a fake graph', async () => {
    stubApi({ nodes: 0 })
    renderApp()
    expect(await screen.findByText('아직 자라난 트리가 없다')).toBeInTheDocument()
    expect(screen.queryByTestId('graph')).not.toBeInTheDocument()
  })

  it('opens at the latest frame and lists what changed with evidence counts and cause', async () => {
    stubApi()
    renderApp()
    expect(await screen.findByTestId('graph')).toHaveAttribute('data-frame', '2')
    await openChanges()
    const fresh = await screen.findByRole('heading', { name: /새로 관측된 것/ })
    const list = within(fresh.parentElement!)
    expect(list.getByText('SK hynix')).toBeInTheDocument()
    expect(list.getByText('재분류')).toBeInTheDocument() // 새 관측이 아닌 변화는 원인 배지
    // 확산 수와 독립 근거 수를 따로 보여준다
    expect(list.getAllByText((_, el) => el?.tagName === 'SPAN' && !el.className && el.textContent === '독립 2 / 확산 2')).toHaveLength(2)
  })

  it('clicking a change opens the node wiki, and wiki links move to the linked node', async () => {
    stubApi()
    renderApp()
    await openChanges()
    fireEvent.click(await screen.findByRole('button', { name: /새 대상.*SK hynix/ }))
    expect(await screen.findByRole('heading', { name: 'SK hynix', level: 2 })).toBeInTheDocument()
    expect(screen.getByText(/위키 v1/)).toBeInTheDocument()
    // 안전하지 않은 링크는 글자로만 남는다
    expect(screen.getByText('나쁜 링크').closest('a')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'HBM' }))
    expect(await screen.findByRole('heading', { name: 'HBM', level: 2 })).toBeInTheDocument()
  })

  it('lines up US and KR tickers of the tree on one time axis and hides bars after the playhead', async () => {
    stubApi()
    renderApp()
    const strip = await screen.findByRole('region', { name: '트리 속 종목' })
    // 구간 시작 직전 종가 대비: NVIDIA 100 → 110, SK하이닉스 200 → 180
    expect(within(strip).getByRole('button', { name: 'NVIDIA US +10.0%' })).toBeInTheDocument()
    expect(within(strip).getByRole('button', { name: 'SK hynix KR −10.0%' })).toBeInTheDocument()

    // 하루 전으로: SK하이닉스는 아직 트리에 없고, NVIDIA는 그때까지 끝난 봉만
    fireEvent.change(screen.getByRole('slider', { name: '재생 시점' }), { target: { value: '1' } })
    expect(await within(strip).findByRole('button', { name: 'NVIDIA US +4.0%' })).toBeInTheDocument()
    expect(within(strip).queryByRole('button', { name: /SK hynix/ })).not.toBeInTheDocument()

    // 종목을 누르면 그 노드의 위키 옆에 시세가 붙는다
    fireEvent.click(within(strip).getByRole('button', { name: /NVIDIA/ }))
    expect(within(strip).getByRole('button', { name: /NVIDIA/ })).toHaveAttribute('aria-pressed', 'true')
    expect(await screen.findByText('일봉 종가')).toBeInTheDocument()
    expect(screen.getByText('2026-10-13 마감')).toBeInTheDocument()
  })

  it('moving the slider back changes the frame and the as-of time of every query', async () => {
    const calls = stubApi()
    renderApp()
    await openChanges()
    fireEvent.click(await screen.findByRole('button', { name: /새 대상.*SK hynix/ }))
    await screen.findByRole('heading', { name: 'SK hynix', level: 2 })
    fireEvent.change(screen.getByRole('slider', { name: '재생 시점' }), { target: { value: '1' } })
    expect(screen.getByTestId('graph')).toHaveAttribute('data-frame', '1')
    // 그 시점에는 아직 없던 노드
    expect(await screen.findByText(/이 시점에는 아직 관측되지 않았다/)).toBeInTheDocument()
    const until = calls.filter((u) => u.pathname === '/api/changes').map((u) => u.searchParams.get('until'))
    expect(until.at(-1)).toBe(fx.T1)
    expect(await screen.findByText('이 기간에 새로 관측되거나 달라진 것이 없다.')).toBeInTheDocument()
  })

  it('edge inspector shows evidence and hides deleted posts', async () => {
    stubApi()
    renderApp()
    fireEvent.click(await screen.findByRole('button', { name: 'pick edge' }))
    expect(await screen.findByRole('link', { name: '원문 보기' })).toHaveAttribute('href', 'https://news.ycombinator.com/item?id=1')
    expect(screen.getByText('“fixture excerpt”')).toBeInTheDocument()
    expect(screen.getByText(/작성자가 지운 글/)).toBeInTheDocument()
    expect(screen.getByText(/커뮤니티 의견 · 미검증/)).toBeInTheDocument()
  })

  it('Focus Pivot: digging into a node grows a new tree from it and shows the path', async () => {
    const calls = stubApi()
    renderApp()
    await openChanges()
    fireEvent.click(await screen.findByRole('button', { name: /새 대상.*SK hynix/ }))
    // 루트가 아닌 노드에는 파고들기 버튼이 있다
    fireEvent.click(await screen.findByRole('button', { name: '여기서 파고들기' }))
    const nav = await screen.findByRole('navigation', { name: '탐색 경로' })
    expect(await within(nav).findByText('HBM')).toHaveAttribute('aria-current', 'page')
    expect(within(nav).getByRole('button', { name: 'NVIDIA' })).toBeInTheDocument()
    expect(window.location.search).toContain('p=prf_hbm')
    // 새 가지의 트리·달라진 점을 그 가지 기준으로 다시 부른다
    expect(calls.some((u) => u.pathname === '/api/frames' && u.searchParams.get('profile') === 'prf_hbm')).toBe(true)
    // 경로의 앞쪽을 누르면 원래 트리로 돌아간다
    fireEvent.click(within(nav).getByRole('button', { name: 'NVIDIA' }))
    expect(window.location.search).not.toContain('p=')
  })
})
