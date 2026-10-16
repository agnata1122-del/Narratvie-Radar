import Graph from 'graphology'
import forceAtlas2 from 'graphology-layout-forceatlas2'
import type { Frames } from '../api'

export type Positions = Record<string, { x: number; y: number }>

function hash(text: string): number {
  let h = 2166136261
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

/**
 * 전체 기간에 한 번이라도 나온 노드·관계로 위치를 한 번 계산한다 (DECISIONS D14, PRD 11.4).
 * 같은 입력이면 항상 같은 위치가 나오도록 시작 위치를 노드 ID에서 정한다.
 */
export function computeLayout(frames: Frames, rootId: string | null): Positions {
  const graph = new Graph({ type: 'undirected', multi: false })
  for (const id of Object.keys(frames.nodes).sort()) {
    const h = hash(id)
    const angle = (h % 3600) / 3600 * Math.PI * 2
    const radius = 1 + (h % 97) / 97
    graph.addNode(id, { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius })
  }
  for (const [id, e] of Object.entries(frames.edges)) {
    if (graph.hasNode(e.source) && graph.hasNode(e.target) && !graph.hasEdge(e.source, e.target)) {
      // 공동 언급은 약하게 당긴다
      graph.addEdgeWithKey(id, e.source, e.target, { weight: e.relation === 'CO_MENTIONED_WITH' ? 0.2 : 1 })
    }
  }
  if (graph.order > 1) {
    forceAtlas2.assign(graph, {
      iterations: 300,
      getEdgeWeight: 'weight',
      settings: { ...forceAtlas2.inferSettings(graph), barnesHutOptimize: false, strongGravityMode: true },
    })
  }
  const positions: Positions = {}
  const origin = rootId && graph.hasNode(rootId) ? graph.getNodeAttributes(rootId) : { x: 0, y: 0 }
  graph.forEachNode((id, attrs) => {
    positions[id] = { x: attrs.x - origin.x, y: attrs.y - origin.y }
  })
  return positions
}
