import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'

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

describe('App shell', () => {
  it('shows each source status from the API instead of claiming live collection', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        Response.json({
          status: 'ok',
          version: '0.2.0',
          sources: [
            {
              id: 'dcinside_stockus',
              display_name: '미주갤',
              access_status: 'not_authorized',
              live_enabled: false,
            },
          ],
        }),
      ),
    )
    renderApp()
    expect(screen.getByRole('heading', { name: 'Narrative Radar' })).toBeInTheDocument()
    expect(await screen.findByText('미주갤 · 수집 꺼짐')).toBeInTheDocument()
  })

  it('shows a disconnected state when the API is unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 502 })))
    renderApp()
    expect(await screen.findByText('API 연결 안 됨')).toBeInTheDocument()
  })
})
