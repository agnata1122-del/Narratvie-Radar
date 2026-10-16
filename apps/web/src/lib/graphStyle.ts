import type { EdgeFrameValue, NodeFrameValue } from '../api'

export type Palette = {
  node: Record<string, string>
  dormant: string
  edgeConfirmed: string
  edgeCandidate: string
  edgeCoMention: string
  highlight: string
  label: string
  surface: string
}

export const NODE_TYPES = ['company', 'industry', 'technology', 'topic', 'event', 'narrative'] as const

export function readPalette(el: Element = document.documentElement): Palette {
  const css = getComputedStyle(el)
  const v = (name: string, fallback: string) => css.getPropertyValue(name).trim() || fallback
  const node: Record<string, string> = {}
  for (const t of NODE_TYPES) node[t] = v(`--nr-node-${t}`, '#666666')
  return {
    node,
    dormant: v('--nr-node-dormant', '#a3acb9'),
    edgeConfirmed: v('--nr-edge-confirmed', '#4b5563'),
    edgeCandidate: v('--nr-edge-candidate', '#9ca3af'),
    edgeCoMention: v('--nr-edge-comention', '#d1d5db'),
    highlight: v('--nr-highlight', '#dc2626'),
    label: v('--nr-label', '#1b1f24'),
    surface: v('--nr-surface', '#ffffff'),
  }
}

/** '#rrggbb' → 'rgba(r, g, b, a)'. 다른 형식은 그대로 둔다. */
export function withAlpha(color: string, alpha: number): string {
  const m = /^#([0-9a-f]{6})$/i.exec(color)
  if (!m) return color
  const n = parseInt(m[1], 16)
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`
}

export type NodeStyleInput = {
  type: string
  value: NodeFrameValue
  isRoot: boolean
  selected: boolean
  highlighted: boolean
}

/** 크기 = 관심도, 색 = 노드 유형, 흐림 = 후보·검토 대기, 회색 = 휴면 (PRD 11.2). */
export function nodeStyle(input: NodeStyleInput, palette: Palette): { size: number; color: string; forceLabel: boolean } {
  const [activity, status, membership] = input.value
  let size = Math.min(26, 5 + 4 * Math.sqrt(Math.max(activity, 0)))
  if (input.isRoot) size = Math.max(size, 14)
  let color = palette.node[input.type] ?? '#666666'
  if (status === 'dormant') color = palette.dormant
  const tentative = membership === 'pending_review' || status === 'candidate'
  if (tentative) color = withAlpha(color, 0.45)
  if (input.highlighted) {
    color = palette.highlight
    size += 3
  }
  if (input.selected) size += 4
  return { size, color, forceLabel: input.isRoot || input.selected || input.highlighted }
}

export type EdgeStyleInput = {
  relation: string
  value: EdgeFrameValue
  highlighted: boolean
  selected: boolean
}

/** 두께 = 강도, 진한 선 = 관측 확정, 연한 선 = 발견 후보, 아주 연한 선 = 공동 언급 (PRD 11.3). */
export function edgeStyle(input: EdgeStyleInput, palette: Palette): { size: number; color: string } {
  const [strength, status] = input.value
  if (input.relation === 'CO_MENTIONED_WITH') {
    return { size: 0.6, color: withAlpha(palette.edgeCoMention, 0.8) }
  }
  const base = Math.min(5, 1 + 0.6 * Math.max(strength, 0))
  if (input.highlighted || input.selected) return { size: base + 1.5, color: palette.highlight }
  if (status === 'confirmed') return { size: base, color: withAlpha(palette.edgeConfirmed, 0.85) }
  if (status === 'weakened') return { size: 0.8, color: withAlpha(palette.edgeCandidate, 0.35) }
  return { size: 0.9, color: withAlpha(palette.edgeCandidate, 0.6) }
}
