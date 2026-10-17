import type { Frames } from '../api'

export type Positions = Record<string, { x: number; y: number }>
export type TreeLayout = { positions: Positions; rings: number[] }

function hash(text: string): number {
  let h = 2166136261
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

/** 노드의 깊이: 가장 최근 프레임의 값, 없으면 전체 프레임 중 가장 얕은 값 */
export function latestDepths(frames: Frames): Record<string, number | null> {
  const depth: Record<string, number | null> = {}
  for (const id of Object.keys(frames.nodes)) depth[id] = null
  for (const frame of frames.frames) {
    for (const [id, v] of Object.entries(frame.nodes)) {
      const d = v[4]
      if (typeof d === 'number') depth[id] = d
    }
  }
  return depth
}

/**
 * 관심사 루트를 가운데 두고 깊이마다 고리에 놓는 방사형 트리 (DECISIONS D23).
 *
 * - 관측 확정·후보 관계(공동 언급 제외)로 루트에서 넓이 우선으로 부모를 정해 펼친 나무를 만든다.
 * - 각 노드는 부모의 부채꼴을 자식 수(잎 수)에 비례해 나눠 가진다. 그래서 같은 가지는 모여 있다.
 * - 깊이는 가장 최근 프레임 값을 쓴다. 재생 중에는 위치가 바뀌지 않고 나타나고 사라질 뿐이다 (D14).
 * - 관계로 닿지 않는 노드(공동 언급만 있는 노드 등)는 가장 바깥 고리에 둔다.
 * 같은 입력이면 항상 같은 그림이 나온다.
 */
export function computeLayout(frames: Frames, rootId: string | null): TreeLayout {
  const ids = Object.keys(frames.nodes).sort()
  if (ids.length === 0) return { positions: {}, rings: [] }
  const root = rootId && frames.nodes[rootId] ? rootId : ids[0]
  const depthOf = latestDepths(frames)

  const neighbors = new Map<string, string[]>()
  const link = (a: string, b: string) => {
    if (!neighbors.has(a)) neighbors.set(a, [])
    neighbors.get(a)!.push(b)
  }
  for (const e of Object.values(frames.edges)) {
    if (e.relation === 'CO_MENTIONED_WITH' || !frames.nodes[e.source] || !frames.nodes[e.target]) continue
    link(e.source, e.target)
    link(e.target, e.source)
  }
  for (const list of neighbors.values()) list.sort()

  // 넓이 우선으로 부모 정하기 (깊이 정보가 있으면 한 단계 얕은 이웃을 부모로)
  const parent = new Map<string, string | null>([[root, null]])
  const level = new Map<string, number>([[root, 0]])
  const queue = [root]
  while (queue.length) {
    const node = queue.shift()!
    for (const next of neighbors.get(node) ?? []) {
      if (parent.has(next)) continue
      parent.set(next, node)
      level.set(next, level.get(node)! + 1)
      queue.push(next)
    }
  }
  const children = new Map<string, string[]>()
  for (const [child, p] of parent) {
    if (p === null) continue
    if (!children.has(p)) children.set(p, [])
    children.get(p)!.push(child)
  }
  // 자식 순서: 깊이 → 이름 (안정된 배치)
  for (const list of children.values()) list.sort((a, b) => frames.nodes[a].label.localeCompare(frames.nodes[b].label) || a.localeCompare(b))

  const leaves = new Map<string, number>()
  const countLeaves = (node: string): number => {
    const kids = children.get(node) ?? []
    const n = kids.length === 0 ? 1 : kids.reduce((sum, k) => sum + countLeaves(k), 0)
    leaves.set(node, n)
    return n
  }
  countLeaves(root)

  const ringOf = (node: string) => Math.max(1, depthOf[node] ?? level.get(node) ?? 1)
  const positions: Positions = { [root]: { x: 0, y: 0 } }
  // 루트의 첫 자식이 위쪽(12시)에서 시작하도록
  const place = (node: string, from: number, to: number) => {
    const kids = children.get(node) ?? []
    const total = kids.reduce((sum, k) => sum + leaves.get(k)!, 0)
    let cursor = from
    kids.forEach((kid, i) => {
      const span = ((to - from) * leaves.get(kid)!) / total
      const angle = cursor + span / 2
      // 같은 고리에서 이웃 라벨이 겹치지 않게 반지름을 조금씩 엇갈린다
      const r = ringOf(kid) + (i % 2 === 0 ? 0 : 0.14)
      positions[kid] = { x: Math.cos(angle) * r, y: Math.sin(angle) * r }
      place(kid, cursor, cursor + span)
      cursor += span
    })
  }
  place(root, -Math.PI / 2, (Math.PI * 3) / 2)

  const placedRings = Object.keys(positions).filter((id) => id !== root).map(ringOf)
  const outer = Math.max(2, ...placedRings) + 1
  const orphans = ids.filter((id) => !positions[id])
  orphans.forEach((id, i) => {
    // 바깥 고리에 고르게 놓되, 시작 각도는 루트마다 다르게 해 안쪽 가지와 겹침을 줄인다
    const angle = (i / orphans.length) * Math.PI * 2 - Math.PI / 2 + ((hash(root) % 100) / 100) * (Math.PI / orphans.length)
    positions[id] = { x: Math.cos(angle) * outer, y: Math.sin(angle) * outer }
  })

  const maxRing = Math.max(1, ...ids.filter((id) => id !== root).map((id) => (positions[id] && !orphans.includes(id) ? ringOf(id) : 0)))
  const rings = Array.from({ length: maxRing }, (_, i) => i + 1)
  return { positions, rings }
}
