// 코드 테스트용 최소 픽스처 (형식 확인용, 실제 수집 글 아님 · DECISIONS D13)
import type { ChangeReport, EdgeDetail, Frames, Health, NodeDetail, Overview } from '../api'

export const T0 = '2026-10-14T00:00:00Z'
export const T1 = '2026-10-15T00:00:00Z'
export const T2 = '2026-10-16T00:00:00Z'

export const health: Health = {
  status: 'ok',
  version: '0.2.0',
  database: 'ok',
  sources: [{ id: 'hackernews', display_name: 'Hacker News', access_status: 'not_authorized', live_enabled: false }],
}

const ROOT_SUMMARY = {
  profile_id: 'prf_1',
  name: 'NVIDIA Research',
  root_label: 'NVIDIA',
  root_node_id: 'nod_nv',
  root_type: 'organization',
  parent_profile_id: null,
  origin: 'registered' as const,
  created_at: T0,
}

export const BRANCH_SUMMARY = {
  profile_id: 'prf_hbm',
  name: 'HBM',
  root_label: 'HBM',
  root_node_id: 'nod_hbm',
  root_type: 'technology',
  parent_profile_id: 'prf_1',
  origin: 'branch' as const,
  created_at: T1,
}

/** 가지(HBM)의 overview: 경로 NVIDIA › HBM */
export function branchOverview(): Overview {
  const base = overview()
  return {
    ...base,
    profile: {
      ...base.profile,
      profile_id: 'prf_hbm',
      name: 'HBM',
      root_key: 'TECH:hbm',
      root_label: 'HBM',
      root_node_id: 'nod_hbm',
      origin: 'branch',
      created_at: T1,
      parent_profile_id: 'prf_1',
    },
    lineage: [ROOT_SUMMARY, BRANCH_SUMMARY],
    children: [],
  }
}

export function overview(nodes = 3, children: (typeof BRANCH_SUMMARY)[] = []): Overview {
  return {
    lineage: [ROOT_SUMMARY],
    children,
    profile: {
      origin: 'registered',
      created_at: T0,
      parent_profile_id: null,
      profile_id: 'prf_1',
      name: 'NVIDIA',
      domain: { id: 'finance', name: '금융·투자', lenses: ['price_overlay', 'shadow_trading'] },
      root_key: 'US:NVDA',
      root_label: 'NVIDIA',
      root_node_id: 'nod_nv',
      max_depth: 2,
      auto_expand: true,
      max_new_nodes_per_day: 15,
      minimum_independent_evidence: 2,
    },
    sources: [{ id: 'hackernews', display_name: 'Hacker News', access_status: 'not_authorized' }],
    time: { start: nodes ? T0 : null, now: T2 },
    counts: { documents: nodes ? 4 : 0, nodes, edges: nodes ? 2 : 0 },
  }
}

export const frames: Frames = {
  nodes: {
    nod_nv: { label: 'NVIDIA', type: 'organization', key: 'US:NVDA' },
    nod_hbm: { label: 'HBM', type: 'technology', key: 'TECH:hbm' },
    nod_skh: { label: 'SK hynix', type: 'organization', key: 'KR:000660' },
  },
  edges: {
    edg_1: { source: 'nod_hbm', target: 'nod_nv', relation: 'SUPPLIES_TO' },
    edg_2: { source: 'nod_skh', target: 'nod_hbm', relation: 'SUPPLIES_TO' },
  },
  frames: [
    { t: T0, nodes: { nod_nv: [0, 'active', 'root', 0, 0] }, edges: {} },
    {
      t: T1,
      nodes: { nod_nv: [1, 'active', 'root', 2, 0], nod_hbm: [1, 'active', 'admitted', 2, 1] },
      edges: { edg_1: [2, 'confirmed', 2] },
    },
    {
      t: T2,
      nodes: {
        nod_nv: [1.5, 'active', 'root', 4, 0],
        nod_hbm: [1.2, 'active', 'admitted', 4, 1],
        nod_skh: [0.8, 'active', 'admitted', 2, 2],
      },
      edges: { edg_1: [1.8, 'confirmed', 2], edg_2: [2, 'confirmed', 2] },
    },
  ],
}

export function changes(since: string, until: string): ChangeReport {
  const later = new Date(until) >= new Date(T2)
  return {
    since,
    until,
    gaps: [],
    items: later
      ? [
          {
            kind: 'new_node',
            label: 'SK hynix',
            node_ids: ['nod_skh'],
            cause: 'observed_new',
            spread_documents: 2,
            independent: 2,
            available_at: T2,
            edge_id: null,
            narrative_id: null,
            detail: { node_type: 'organization', depth: 2 },
            evidence: [
              { document_id: 'doc_1', source: 'hackernews', url: 'https://news.ycombinator.com/item?id=1', published_at: T2, excerpt: 'fixture excerpt' },
            ],
          },
          {
            kind: 'new_relation',
            label: 'SK hynix → HBM',
            node_ids: ['nod_skh', 'nod_hbm'],
            cause: 'reprocess',
            spread_documents: 2,
            independent: 2,
            available_at: T2,
            edge_id: 'edg_2',
            narrative_id: null,
            detail: { relation: 'SUPPLIES_TO' },
            evidence: [],
          },
        ]
      : [],
  }
}

export function nodeDetail(id: string): NodeDetail {
  const label = frames.nodes[id]?.label ?? id
  return {
    node: {
      node_id: id,
      label,
      node_type: 'organization',
      status: 'active',
      membership: 'admitted',
      depth: 1,
      activity: 1.2,
      mentions_7d: 2,
      independent_7d: 2,
      share_7d: 0.08,
      first_seen: T1,
      last_mention_at: T2,
    },
    wiki: {
      version: 1,
      available_at: T1,
      generator: 'facts.v1',
      sections: [
        { key: 'overview', title: '개요', markdown: `**${label}** · 상태: 활성`, links: [] },
        {
          key: 'related',
          title: '관련 대상',
          markdown: '- → [[HBM]] · 공급 · 관측 확정 (독립 근거 2)\n- [나쁜 링크](javascript:alert)',
          links: [{ label: 'HBM', node_id: 'nod_hbm' }],
        },
      ],
    },
    narrative: null,
  }
}

export const edgeDetail: EdgeDetail = {
  edge_id: 'edg_2',
  source: { node_id: 'nod_skh', label: 'SK hynix' },
  target: { node_id: 'nod_hbm', label: 'HBM' },
  relation: 'SUPPLIES_TO',
  evidence: [
    { document_id: 'doc_1', source: 'hackernews', published_at: T2, deleted: false, url: 'https://news.ycombinator.com/item?id=1', excerpt: 'fixture excerpt', evidence_status: 'community_opinion' },
    { document_id: 'doc_2', source: 'hackernews', published_at: T1, deleted: true, url: null, excerpt: null, evidence_status: null },
  ],
}
