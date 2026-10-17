import type { EdgeFrameValue, NodeFrameValue } from '../api'
import { parseColor, toCss, withAlpha } from './motion'

export { withAlpha }

/**
 * 노드 유형 → 색 묶음. 유형마다 색을 주면 모든 쌍 색각 검사를 통과하지 못해 3묶음으로 줄였다
 * (index.css 머리말, DECISIONS D20). 행위자(조직·인물) / 대상(제품·기술·주제·사건·장소) / 내러티브.
 */
export type SeriesGroup = 'entity' | 'concept' | 'narrative'

export const TYPE_GROUP: Record<string, SeriesGroup> = {
  organization: 'entity',
  person: 'entity',
  product: 'concept',
  technology: 'concept',
  topic: 'concept',
  event: 'concept',
  place: 'concept',
  narrative: 'narrative',
  // 예전 값
  company: 'entity',
  industry: 'concept',
}

export const SERIES_GROUPS: SeriesGroup[] = ['entity', 'concept', 'narrative']

export type Palette = {
  series: Record<SeriesGroup, string>
  dormant: string
  edgeConfirmed: string
  edgeCandidate: string
  edgeCoMention: string
  focus: string
  label: string
  surface: string
}

export function readPalette(el: Element = document.documentElement): Palette {
  const css = getComputedStyle(el)
  const v = (name: string, fallback: string) => css.getPropertyValue(name).trim() || fallback
  return {
    series: {
      entity: v('--nr-series-entity', '#2a78d6'),
      concept: v('--nr-series-concept', '#eb6834'),
      narrative: v('--nr-series-narrative', '#1baf7a'),
    },
    dormant: v('--nr-node-dormant', '#c3c8cf'),
    edgeConfirmed: v('--nr-edge-confirmed', '#4a5361'),
    edgeCandidate: v('--nr-edge-candidate', '#7b8494'),
    edgeCoMention: v('--nr-edge-comention', '#b9bec6'),
    focus: v('--nr-focus', '#0f1419'),
    label: v('--nr-label', '#2b323c'),
    surface: v('--nr-surface', '#ffffff'),
  }
}

export type NodeStyle = { size: number; color: string; shape: 'circle' | 'diamond' }

/** 크기 = 관심도, 색 = 유형 묶음, 다이아몬드 = 내러티브, 회색 = 휴면, 흐림 = 후보·검토 대기 (PRD 11.2). */
export function nodeStyle(input: { type: string; value: NodeFrameValue; isRoot: boolean }, palette: Palette): NodeStyle {
  const [activity, status, membership] = input.value
  const group = TYPE_GROUP[input.type] ?? 'concept'
  let size = Math.min(24, 4.5 + 3.6 * Math.sqrt(Math.max(activity, 0)))
  if (input.isRoot) size = Math.max(size, 13)
  let color = status === 'dormant' ? palette.dormant : palette.series[group]
  const tentative = membership === 'pending_review' || status === 'candidate'
  if (tentative) color = withAlpha(color, 0.42)
  else color = toCss(parseColor(color))
  return { size: group === 'narrative' ? size * 1.15 : size, color, shape: group === 'narrative' ? 'diamond' : 'circle' }
}

export type EdgeStyle = { size: number; color: string; gap: number }

/** 두께 = 강도, 실선 = 관측 확정, 점선 = 발견 후보, 아주 옅은 선 = 공동 언급 (PRD 11.3). */
export function edgeStyle(input: { relation: string; value: EdgeFrameValue; highlighted: boolean }, palette: Palette): EdgeStyle {
  const [strength, status] = input.value
  if (input.relation === 'CO_MENTIONED_WITH') return { size: 0.6, color: withAlpha(palette.edgeCoMention, 0.7), gap: 0 }
  const confirmedSize = Math.min(4, 0.9 + 0.5 * Math.max(strength, 0))
  if (input.highlighted) return { size: Math.max(confirmedSize, 1.4) + 0.8, color: withAlpha(palette.focus, 0.9), gap: status === 'confirmed' ? 0 : 3 }
  if (status === 'confirmed') return { size: confirmedSize, color: withAlpha(palette.edgeConfirmed, 0.7), gap: 0 }
  if (status === 'weakened') return { size: 0.8, color: withAlpha(palette.edgeCandidate, 0.4), gap: 3 }
  return { size: 1, color: withAlpha(palette.edgeCandidate, 0.85), gap: 3 }
}
