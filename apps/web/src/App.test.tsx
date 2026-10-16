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
    vi.fn(async (input: string) => {
      const url = new URL(input, 'http://localhost')
      calls.push(url)
      if (failAll) return new Response('', { status: 502 })
      const path = url.pathname.replace(/^\/api/, '')
      const q = url.searchParams
      if (path === '/health') return Response.json(fx.health)
      if (path === '/overview') return Response.json(fx.overview(nodes))
      if (path === '/viewer/visit') return Response.json({ viewer_id: 'vwr_1', previous_seen_at: null })
      if (path === '/frames') return Response.json(fx.frames)
      if (path === '/events') return Response.json([{ t: fx.T1, type: 'NODE_CREATED', cause: 'observed_new', node_id: 'nod_hbm', edge_id: null }])
      if (path === '/gaps') return Response.json([])
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
    expect(await screen.findByText('Hacker News · 수집 꺼짐')).toBeInTheDocument()
  })

  it('shows a disconnected state when the API is unreachable', async () => {
    stubApi({ failAll: true })
    renderApp()
    expect(await screen.findByText('API 연결 안 됨')).toBeInTheDocument()
  })

  it('explains the empty state instead of drawing a fake graph', async () => {
    stubApi({ nodes: 0 })
    renderApp()
    expect(await screen.findByText('아직 그려질 그래프가 없다')).toBeInTheDocument()
    expect(screen.queryByTestId('graph')).not.toBeInTheDocument()
  })

  it('opens at the latest frame and lists what changed with evidence counts and cause', async () => {
    stubApi()
    renderApp()
    expect(await screen.findByTestId('graph')).toHaveAttribute('data-frame', '2')
    const fresh = await screen.findByRole('heading', { name: '새로 관측된 것' })
    const list = within(fresh.parentElement!)
    expect(list.getByText('SK hynix')).toBeInTheDocument()
    expect(list.getByText('재분류')).toBeInTheDocument() // 새 관측이 아닌 변화는 원인 배지
    expect(list.getAllByText(/확산 2건 · 독립 근거 2/)).toHaveLength(2)
  })

  it('clicking a change opens the node wiki, and wiki links move to the linked node', async () => {
    stubApi()
    renderApp()
    fireEvent.click(await screen.findByRole('button', { name: /새 대상.*SK hynix/ }))
    expect(await screen.findByRole('heading', { name: 'SK hynix', level: 2 })).toBeInTheDocument()
    expect(screen.getByText(/위키 v1/)).toBeInTheDocument()
    // 안전하지 않은 링크는 글자로만 남는다
    expect(screen.getByText('나쁜 링크').closest('a')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'HBM' }))
    expect(await screen.findByRole('heading', { name: 'HBM', level: 2 })).toBeInTheDocument()
  })

  it('moving the slider back changes the frame and the as-of time of every query', async () => {
    const calls = stubApi()
    renderApp()
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
    expect(await screen.findByText('“fixture excerpt”')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '원문 보기' })).toHaveAttribute('href', 'https://news.ycombinator.com/item?id=1')
    expect(screen.getByText(/작성자가 지운 글/)).toBeInTheDocument()
    expect(screen.getByText(/커뮤니티 의견 · 미검증/)).toBeInTheDocument()
  })
})
