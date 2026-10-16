import { describe, expect, it } from 'vitest'
import { frames } from '../test/fixtures'
import { frameIndexAt, nodeIdsByLabel, positionIn } from './frames'
import { edgeStyle, nodeStyle, type Palette } from './graphStyle'
import { computeLayout } from './layout'
import { defaultRange } from './time'
import { safeHref } from './url'

const palette: Palette = {
  node: { company: '#2563eb', technology: '#7c3aed' },
  dormant: '#a3acb9',
  edgeConfirmed: '#4b5563',
  edgeCandidate: '#9ca3af',
  edgeCoMention: '#d1d5db',
  highlight: '#dc2626',
  label: '#1b1f24',
  surface: '#ffffff',
}

describe('layout', () => {
  it('is deterministic and centred on the root', () => {
    const a = computeLayout(frames, 'nod_nv')
    const b = computeLayout(frames, 'nod_nv')
    expect(a).toEqual(b)
    expect(a.nod_nv).toEqual({ x: 0, y: 0 })
    expect(Object.keys(a).sort()).toEqual(['nod_hbm', 'nod_nv', 'nod_skh'])
  })
})

describe('graph style', () => {
  const base = { type: 'company', isRoot: false, selected: false, highlighted: false }
  it('grows with activity and greys out dormant nodes', () => {
    const quiet = nodeStyle({ ...base, value: [0, 'active', 'admitted', 0] }, palette)
    const busy = nodeStyle({ ...base, value: [4, 'active', 'admitted', 9] }, palette)
    expect(busy.size).toBeGreaterThan(quiet.size)
    expect(nodeStyle({ ...base, value: [1, 'dormant', 'admitted', 0] }, palette).color).toBe('#a3acb9')
  })
  it('fades nodes waiting for review', () => {
    expect(nodeStyle({ ...base, value: [1, 'active', 'pending_review', 1] }, palette).color).toBe('rgba(37, 99, 235, 0.45)')
  })
  it('draws confirmed relations thicker than candidates', () => {
    const confirmed = edgeStyle({ relation: 'SUPPLIES_TO', value: [2, 'confirmed', 2], highlighted: false, selected: false }, palette)
    const candidate = edgeStyle({ relation: 'SUPPLIES_TO', value: [2, 'candidate', 1], highlighted: false, selected: false }, palette)
    expect(confirmed.size).toBeGreaterThan(candidate.size)
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
})

describe('safeHref', () => {
  it('allows only http(s)', () => {
    expect(safeHref('https://bsky.app/profile/x/post/y')).toBe('https://bsky.app/profile/x/post/y')
    expect(safeHref('javascript:alert(1)')).toBeNull()
    expect(safeHref('not a url')).toBeNull()
  })
})
