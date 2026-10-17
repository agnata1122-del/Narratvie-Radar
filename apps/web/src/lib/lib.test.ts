import { describe, expect, it } from 'vitest'
import type { PriceBarRow } from '../api'
import { frames } from '../test/fixtures'
import { binEvents, frameIndexAt, nodeIdsByLabel, positionIn } from './frames'
import { edgeStyle, nodeStyle, type Palette } from './graphStyle'
import { computeLayout } from './layout'
import { mixColor, parseColor, toCss } from './motion'
import { changeSince, changeTone, formatChange, formatPrice, sparkPath, visibleBars } from './prices'
import { defaultRange, relativeTime } from './time'
import { safeHref } from './url'

const palette: Palette = {
  series: { entity: '#2a78d6', concept: '#eb6834', narrative: '#1baf7a' },
  dormant: '#a3acb9',
  edgeConfirmed: '#4b5563',
  edgeCandidate: '#9ca3af',
  edgeCoMention: '#d1d5db',
  focus: '#0f1419',
  label: '#1b1f24',
  surface: '#ffffff',
}

describe('radial tree layout', () => {
  it('puts the root at the centre and each depth on its own ring, deterministically', () => {
    const a = computeLayout(frames, 'nod_nv')
    expect(a).toEqual(computeLayout(frames, 'nod_nv'))
    const r = (id: string) => Math.hypot(a.positions[id].x, a.positions[id].y)
    expect(a.positions.nod_nv).toEqual({ x: 0, y: 0 })
    expect(r('nod_hbm')).toBeCloseTo(1, 0)
    expect(r('nod_skh')).toBeGreaterThan(1.8)
    expect(a.rings).toEqual([1, 2])
  })
  it('re-centres on whichever node becomes the root (Focus Pivot)', () => {
    const b = computeLayout(frames, 'nod_hbm')
    expect(b.positions.nod_hbm).toEqual({ x: 0, y: 0 })
  })
})

describe('graph style', () => {
  const base = { type: 'organization', isRoot: false }
  it('grows with activity and greys out dormant nodes', () => {
    const quiet = nodeStyle({ ...base, value: [0, 'active', 'admitted', 0] }, palette)
    const busy = nodeStyle({ ...base, value: [4, 'active', 'admitted', 9] }, palette)
    expect(busy.size).toBeGreaterThan(quiet.size)
    expect(nodeStyle({ ...base, value: [1, 'dormant', 'admitted', 0] }, palette).color).toBe('rgba(163, 172, 185, 1)')
  })
  it('fades nodes waiting for review and draws narratives as diamonds', () => {
    expect(nodeStyle({ ...base, value: [1, 'active', 'pending_review', 1] }, palette).color).toBe('rgba(42, 120, 214, 0.42)')
    expect(nodeStyle({ type: 'narrative', isRoot: false, value: [1, 'active', 'admitted', 1] }, palette).shape).toBe('diamond')
    // 유형 8종은 3색 묶음으로 간다 (모든 쌍 색각 검사). 인물은 조직과 같은 행위자 묶음
    expect(nodeStyle({ type: 'person', isRoot: false, value: [1, 'active', 'admitted', 1] }, palette).color).toBe('rgba(42, 120, 214, 1)')
    expect(nodeStyle({ type: 'place', isRoot: false, value: [1, 'active', 'admitted', 1] }, palette).color).toBe('rgba(235, 104, 52, 1)')
  })
  it('draws confirmed relations solid and thicker, candidates dashed', () => {
    const confirmed = edgeStyle({ relation: 'SUPPLIES_TO', value: [2, 'confirmed', 2], highlighted: false }, palette)
    const candidate = edgeStyle({ relation: 'SUPPLIES_TO', value: [2, 'candidate', 1], highlighted: false }, palette)
    expect(confirmed.size).toBeGreaterThan(candidate.size)
    expect(confirmed.gap).toBe(0)
    expect(candidate.gap).toBeGreaterThan(0)
  })
})

describe('motion helpers', () => {
  it('parses and mixes colours for tweens', () => {
    expect(parseColor('#2a78d6')).toEqual([42, 120, 214, 1])
    expect(parseColor('rgba(10, 20, 30, 0.5)')).toEqual([10, 20, 30, 0.5])
    expect(toCss(mixColor([0, 0, 0, 0], [200, 100, 50, 1], 0.5))).toBe('rgba(100, 50, 25, 0.5)')
  })
})

describe('time and frames', () => {
  it('limits the range to the recorded period', () => {
    const r = defaultRange('2026-10-15T00:00:00Z', '2026-10-16T00:00:00Z', 14)
    expect(r).toEqual({ start: '2026-10-15T00:00:00.000Z', end: '2026-10-16T00:00:00.000Z' })
    const r2 = defaultRange('2026-01-01T00:00:00Z', '2026-10-16T00:00:00Z', 7)
    expect(r2.start).toBe('2026-10-09T00:00:00.000Z')
  })
  it('finds the frame at or before a time', () => {
    expect(frameIndexAt(frames.frames, '2026-10-15T12:00:00Z')).toBe(1)
    expect(frameIndexAt(frames.frames, '2020-01-01T00:00:00Z')).toBe(0)
    expect(positionIn('2026-10-14T00:00:00Z', '2026-10-16T00:00:00Z', '2026-10-15T00:00:00Z')).toBe(0.5)
    expect(nodeIdsByLabel(frames).get('HBM')).toBe('nod_hbm')
  })
  it('counts graph changes per interval between frames, ignoring wiki revisions', () => {
    const times = frames.frames.map((f) => f.t)
    const bins = binEvents(times, [
      { t: '2026-10-14T06:00:00Z', type: 'NODE_CREATED', cause: 'observed_new', node_id: 'n', edge_id: null },
      { t: '2026-10-15T12:00:00Z', type: 'EDGE_CONFIRMED', cause: 'observed_new', node_id: null, edge_id: 'e' },
      { t: '2026-10-15T13:00:00Z', type: 'WIKI_REVISED', cause: 'observed_new', node_id: 'n', edge_id: null },
    ])
    expect(bins.map((b) => [b.total, b.nodes, b.edges])).toEqual([
      [1, 1, 0],
      [1, 0, 1],
    ])
  })
  it('describes how long ago something happened', () => {
    expect(relativeTime('2026-10-16T00:00:00Z', '2026-10-16T03:00:00Z')).toBe('3시간 전')
    expect(relativeTime('2026-10-16T00:00:00Z', '2026-10-16T00:20:00Z')).toBe('20분 전')
    expect(relativeTime('2026-10-14T00:00:00Z', '2026-10-16T00:00:00Z')).toBe('2일 전')
  })
})

describe('safeHref', () => {
  it('allows only http(s)', () => {
    expect(safeHref('https://bsky.app/profile/x/post/y')).toBe('https://bsky.app/profile/x/post/y')
    expect(safeHref('javascript:alert(1)')).toBeNull()
    expect(safeHref('not a url')).toBeNull()
  })
})

describe('prices', () => {
  const bars: PriceBarRow[] = [
    ['2026-10-12', 100, '2026-10-13T04:00:00Z'],
    ['2026-10-13', 104, '2026-10-14T04:00:00Z'],
    ['2026-10-14', 110, '2026-10-15T04:00:00Z'],
  ]

  it('never shows a bar before its trading day ended', () => {
    expect(visibleBars(bars, '2026-10-14T03:59:00Z').map((b) => b[0])).toEqual(['2026-10-12'])
    expect(visibleBars(bars, '2026-10-15T04:00:00Z')).toHaveLength(3)
  })

  it('measures change from the last close before the range start', () => {
    expect(changeSince(bars, '2026-10-14T00:00:00Z')).toBeCloseTo(10)
    expect(changeSince(bars, '2026-01-01T00:00:00Z')).toBeCloseTo(10) // 기준이 없으면 첫 봉
    expect(changeSince([], '2026-10-14T00:00:00Z')).toBeNull()
    expect(formatChange(-3.21)).toBe('−3.2%')
    expect(formatChange(null)).toBe('—')
    expect(changeTone(0.01)).toBe('flat')
  })

  it('places every series on the same time axis', () => {
    const d = sparkPath(bars, '2026-10-13T04:00:00Z', '2026-10-15T04:00:00Z', 100, 20, 0)
    expect(d).toBe('M0.0,20.0 L50.0,12.0 L100.0,0.0')
    // 구간 앞의 봉은 기준 하나만 왼쪽 끝에 남는다
    const later = sparkPath(bars, '2026-10-14T12:00:00Z', '2026-10-15T04:00:00Z', 100, 20, 0)
    expect(later).toBe('M0.0,20.0 L100.0,0.0')
    expect(formatPrice(123456, 'KRW', 'KR')).toBe('123,456원')
    expect(formatPrice(12.5, null, 'US')).toBe('12.50')
  })
})

