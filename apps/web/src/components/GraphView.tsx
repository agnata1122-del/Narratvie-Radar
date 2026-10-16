import Graph from 'graphology'
import { useEffect, useRef } from 'react'
import Sigma, { DEFAULT_STYLES } from 'sigma'
import type { Frames } from '../api'
import { edgeStyle, nodeStyle, readPalette, type Palette } from '../lib/graphStyle'
import type { Positions } from '../lib/layout'

export type Selection = { kind: 'node' | 'edge'; id: string } | null
export type Highlight = { nodeIds: string[]; edgeId: string | null } | null

type NodeAttrs = {
  x: number
  y: number
  size: number
  color: string
  label: string
  hidden: boolean
  forceLabel: boolean
  zIndex: number
}
type EdgeAttrs = { size: number; color: string; hidden: boolean; zIndex: number }

export type GraphViewProps = {
  frames: Frames
  frameIndex: number
  positions: Positions
  rootId: string | null
  selection: Selection
  highlight: Highlight
  showCoMention: boolean
  showPending: boolean
  onSelect: (selection: Selection) => void
}

// 내러티브 명제처럼 긴 라벨은 그래프에서 줄이고, 전체 문장은 인스펙터에서 보여준다
const MAX_LABEL = 28
const shortLabel = (text: string) => (text.length > MAX_LABEL ? `${text.slice(0, MAX_LABEL - 1)}…` : text)

const hiddenOr = (visible: 'visible') => (a: { hidden?: boolean }) => (a.hidden ? 'hidden' : visible)

/**
 * 전체 기간 노드·관계를 한 번 올려 두고, 프레임마다 보이기/숨기기와 크기·색만 바꾼다.
 * 위치가 고정이라 재생 중에 그림이 흔들리지 않는다 (DECISIONS D14).
 */
export default function GraphView(props: GraphViewProps) {
  const container = useRef<HTMLDivElement>(null)
  const sigma = useRef<Sigma<NodeAttrs, EdgeAttrs> | null>(null)
  const graph = useRef<Graph<NodeAttrs, EdgeAttrs> | null>(null)
  const palette = useRef<Palette | null>(null)
  const onSelect = useRef(props.onSelect)
  useEffect(() => {
    onSelect.current = props.onSelect
  }, [props.onSelect])

  const { frames, positions } = props

  // 데이터 범위가 바뀌면 그래프를 새로 만든다
  useEffect(() => {
    if (!container.current) return
    const p = readPalette()
    palette.current = p
    const g = new Graph<NodeAttrs, EdgeAttrs>({ type: 'directed', multi: true })
    for (const [id, meta] of Object.entries(frames.nodes)) {
      const pos = positions[id] ?? { x: 0, y: 0 }
      g.addNode(id, { ...pos, size: 4, color: p.dormant, label: shortLabel(meta.label), hidden: true, forceLabel: false, zIndex: 0 })
    }
    for (const [id, meta] of Object.entries(frames.edges)) {
      if (g.hasNode(meta.source) && g.hasNode(meta.target)) {
        g.addDirectedEdgeWithKey(id, meta.source, meta.target, { size: 1, color: p.edgeCandidate, hidden: true, zIndex: 0 })
      }
    }
    graph.current = g
    const s = new Sigma<NodeAttrs, EdgeAttrs>(g, container.current, {
      styles: {
        nodes: {
          ...DEFAULT_STYLES.nodes,
          size: { attribute: 'size', defaultValue: 4 },
          visibility: hiddenOr('visible'),
          labelVisibility: (a: NodeAttrs, state: { isHovered: boolean }) =>
            a.hidden ? 'hidden' : a.forceLabel || state.isHovered ? 'visible' : 'auto',
          labelColor: p.label,
          backdropColor: p.surface,
          zIndex: { attribute: 'zIndex', defaultValue: 0 },
          cursor: 'pointer',
        },
        edges: {
          ...DEFAULT_STYLES.edges,
          visibility: hiddenOr('visible'),
          zIndex: { attribute: 'zIndex', defaultValue: 0 },
          cursor: 'pointer',
        },
      },
      settings: {
        renderEdgeLabels: false,
        enableEdgeEvents: true,
        labelRenderedSizeThreshold: 4,
        labelDensity: 0.6,
        stagePadding: 70,
        autoRescale: true,
        // 크기는 화면 픽셀 기준 (기본값 positions는 좌표 단위라 레이아웃 크기에 따라 달라진다)
        itemSizesReference: 'screen',
      },
    })
    s.on('clickNode', ({ node }) => onSelect.current({ kind: 'node', id: node }))
    s.on('clickEdge', ({ edge }) => onSelect.current({ kind: 'edge', id: edge }))
    s.on('clickStage', () => onSelect.current(null))
    sigma.current = s
    return () => {
      s.kill()
      sigma.current = null
      graph.current = null
    }
  }, [frames, positions])

  // 프레임·선택·필터가 바뀌면 속성만 갱신한다
  const { frameIndex, rootId, selection, highlight, showCoMention, showPending } = props
  useEffect(() => {
    const g = graph.current
    const p = palette.current
    if (!g || !p) return
    const frame = frames.frames[frameIndex]
    if (!frame) return
    const lit = new Set(highlight?.nodeIds ?? [])
    g.forEachNode((id, attrs) => {
      const value = frame.nodes[id]
      const pending = value && (value[2] === 'pending_review' || value[1] === 'candidate')
      if (!value || (!showPending && pending && id !== rootId)) {
        g.mergeNodeAttributes(id, { hidden: true, forceLabel: false })
        return
      }
      const isSelected = selection?.kind === 'node' && selection.id === id
      const style = nodeStyle(
        { type: frames.nodes[id]?.type ?? 'topic', value, isRoot: id === rootId, selected: isSelected, highlighted: lit.has(id) },
        p,
      )
      g.mergeNodeAttributes(id, {
        ...style,
        label: attrs.label,
        hidden: false,
        zIndex: isSelected || lit.has(id) ? 2 : id === rootId ? 1 : 0,
      })
    })
    g.forEachEdge((id, _attrs, source, target) => {
      const value = frame.edges[id]
      const relation = frames.edges[id]?.relation ?? 'RELATED_TO'
      const endpointsShown = !g.getNodeAttribute(source, 'hidden') && !g.getNodeAttribute(target, 'hidden')
      if (!value || !endpointsShown || (!showCoMention && relation === 'CO_MENTIONED_WITH')) {
        g.mergeEdgeAttributes(id, { hidden: true })
        return
      }
      const isSelected = selection?.kind === 'edge' && selection.id === id
      const isLit = highlight?.edgeId === id
      g.mergeEdgeAttributes(id, {
        ...edgeStyle({ relation, value, highlighted: isLit, selected: isSelected }, p),
        hidden: false,
        zIndex: isSelected || isLit ? 2 : value[1] === 'confirmed' ? 1 : 0,
      })
    })
    sigma.current?.refresh()
  }, [frames, frameIndex, rootId, selection, highlight, showCoMention, showPending, positions])

  return (
    <div
      ref={container}
      className="absolute inset-0"
      role="img"
      aria-label="관측된 대상과 연결 그래프. 노드나 선을 누르면 오른쪽에 위키와 근거가 열린다."
      data-testid="graph-canvas"
    />
  )
}
