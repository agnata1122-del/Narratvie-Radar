export type SourceStatus = {
  id: string
  display_name: string
  access_status: 'not_authorized' | 'test_mode' | 'live' | 'paused' | 'blocked'
  live_enabled: boolean
}

export type Health = {
  status: 'ok'
  version: string
  database: 'ok' | 'uninitialized'
  sources: SourceStatus[]
}

export async function fetchHealth(signal?: AbortSignal): Promise<Health> {
  const res = await fetch('/api/health', { signal })
  if (!res.ok) {
    throw new Error(`health check failed: ${res.status}`)
  }
  return (await res.json()) as Health
}
