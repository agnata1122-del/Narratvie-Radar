export type AccessStatus = 'not_authorized' | 'test_mode' | 'live' | 'paused' | 'blocked' | 'stopped'

export type SourceStatus = {
  id: string
  display_name: string
  access_status: AccessStatus
  live_enabled: boolean
}

export type Health = {
  status: 'ok'
  version: string
  database: 'ok' | 'uninitialized'
  sources: SourceStatus[]
}

export type Overview = {
  profile: {
    profile_id: string
    name: string
    root_key: string
    root_label: string
    root_node_id: string | null
    max_depth: number
    auto_expand: boolean
    max_new_nodes_per_day: number
    minimum_independent_evidence: number
  }
  sources: { id: string; display_name: string; access_status: AccessStatus }[]
  time: { start: string | null; now: string }
  counts: { documents: number; nodes: number; edges: number }
}

export type Visit = { viewer_id: string; previous_seen_at: string | null }

// 프레임 값: 노드 [관심도, 상태, 포함 여부, 최근 7일 언급], 관계 [강도, 상태, 독립 근거]
export type NodeFrameValue = [number, string, string, number]
export type EdgeFrameValue = [number, string, number]

export type Frames = {
  nodes: Record<string, { label: string; type: string; key: string }>
  edges: Record<string, { source: string; target: string; relation: string }>
  frames: {
    t: string
    nodes: Record<string, NodeFrameValue>
    edges: Record<string, EdgeFrameValue>
  }[]
}

export type EvidenceRef = {
  document_id: string
  source: string
  url: string
  published_at: string
  excerpt: string | null
}

export type ChangeItem = {
  kind:
    | 'new_narrative'
    | 'narrative_shift'
    | 'new_node'
    | 'new_relation'
    | 'attention_up'
    | 'attention_down'
  label: string
  node_ids: string[]
  cause: string
  spread_documents: number
  independent: number
  available_at: string | null
  edge_id: string | null
  narrative_id: string | null
  detail: Record<string, unknown>
  evidence: EvidenceRef[]
}

export type ChangeReport = {
  since: string
  until: string
  items: ChangeItem[]
  gaps: { source_adapter_id: string; start: string; end: string; status: string; note: string | null }[]
}

export type WikiSection = {
  key: string
  title: string
  markdown: string
  links: { label: string; node_id: string }[]
}

export type NodeDetail = {
  node: {
    node_id: string
    label: string
    node_type: string
    status: string
    membership: string
    depth: number | null
    activity: number
    mentions_7d: number
    independent_7d: number
    share_7d: number
    first_seen: string
    last_mention_at: string | null
  } | null
  wiki: { version: number; available_at: string; generator: string; sections: WikiSection[] } | null
  narrative: {
    proposition: string
    state: string | null
    supports_recent: number
    contradicts_recent: number
  } | null
}

export type EdgeDetail = {
  edge_id: string
  source: { node_id: string; label: string }
  target: { node_id: string; label: string }
  relation: string
  evidence: {
    document_id: string
    source: string
    published_at: string
    deleted: boolean
    url: string | null
    excerpt: string | null
    evidence_status: string | null
  }[]
}

export type GraphEventRow = { t: string; type: string; cause: string; node_id: string | null; edge_id: string | null }
export type Gap = ChangeReport['gaps'][number]

async function getJson<T>(path: string, params?: Record<string, string>, signal?: AbortSignal): Promise<T> {
  const query = params ? `?${new URLSearchParams(params)}` : ''
  const res = await fetch(`/api${path}${query}`, { signal, credentials: 'same-origin' })
  if (!res.ok) throw new Error(`${path} failed: ${res.status}`)
  return (await res.json()) as T
}

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: body === undefined ? undefined : { 'content-type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`${path} failed: ${res.status}`)
  return (await res.json()) as T
}

export const api = {
  health: (signal?: AbortSignal) => getJson<Health>('/health', undefined, signal),
  overview: (signal?: AbortSignal) => getJson<Overview>('/overview', undefined, signal),
  visit: () => postJson<Visit>('/viewer/visit'),
  frames: (start: string, end: string, steps: number, signal?: AbortSignal) =>
    getJson<Frames>('/frames', { start, end, steps: String(steps), include_pending: 'true' }, signal),
  changes: (since: string, until: string, signal?: AbortSignal) =>
    getJson<ChangeReport>('/changes', { since, until }, signal),
  events: (start: string, end: string, signal?: AbortSignal) =>
    getJson<GraphEventRow[]>('/events', { start, end }, signal),
  gaps: (start: string, end: string, signal?: AbortSignal) => getJson<Gap[]>('/gaps', { start, end }, signal),
  node: (id: string, asOf: string, signal?: AbortSignal) =>
    getJson<NodeDetail>(`/nodes/${encodeURIComponent(id)}`, { as_of: asOf }, signal),
  edge: (id: string, asOf: string, signal?: AbortSignal) =>
    getJson<EdgeDetail>(`/edges/${encodeURIComponent(id)}`, { as_of: asOf }, signal),
  overlay: (targetId: string, decision: 'rejected' | 'hidden' | 'approved') =>
    postJson<{ status: string }>('/overlays', { target_id: targetId, decision }),
  feedback: (targetType: string, targetId: string, rating: -1 | 0 | 1) =>
    postJson<{ status: string }>('/feedback', { target_type: targetType, target_id: targetId, rating }),
}

// 헬스 체크는 기존 화면과 테스트에서 그대로 쓴다
export const fetchHealth = api.health
