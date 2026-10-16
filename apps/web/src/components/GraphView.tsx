import Graph from 'graphology'
import { useEffect, useRef, useState } from 'react'
import Sigma, { DEFAULT_STYLES } from 'sigma'
import { layerDashed, layerFill, pathLine, sdfCircle, sdfDiamond } from 'sigma/rendering'
import type { Frames } from '../api'
import { TYPE_GROUP, edgeStyle, nodeStyle, readPalette, type Palette } from '../lib/graphStyle'
import { MEMBERSHIP_LABEL, NODE_STATUS_LABEL, NODE_TYPE_LABEL, label } from '../lib/labels'
import type { Positions } from '../lib/layout'
import {
  easeInOutCubic,
  easeOutBack,
  easeOutCubic,
  lerp,
  mixColor,
  parseColor,
  prefersReducedMotion,
  toCss,
  type RGBA,
} from '../lib/motion'
import { FitIcon, ZoomInIcon, ZoomOutIcon } from './icons'

export type Selection = { kind: 'node' | 'edge'; id: string } | null
export type Highlight = { nodeIds: string[]; edgeId: string | null } | null

type NodeAttrs = {
  x: number
  y: number
  size: number
  color: string
  label: string
  shape: string
  hidden: boolean
  forceLabel: boolean
  zIndex: number
}
type EdgeAttrs = { size: number; color: string; dash: number; gap: number; hidden: boolean; zIndex: number }

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
  /** 프레임이 바뀔 때 노드·선이 옮겨 가는 시간 (재생 속도에 맞춘다) */
  transitionMs: number
  /** 테마가 바뀌면 캔버스 색을 다시 읽는다 */
  theme: string
}

type Vis = { size: number; color: RGBA }
type Tween = { from: Vis; to: Vis; start: number; dur: number; ease: (t: number) => number; hideAtEnd: boolean }

const PULSE_MS = 1500
const BREATH_MS = 2400
const MAX_LABEL = 28
const LABEL_FONT = "'Pretendard Variable', Pretendard, system-ui, sans-serif"

// 내러티브 명제처럼 긴 라벨은 그래프에서 줄이고, 전체 문장은 인스펙터에서 보여준다
const shortLabel = (text: string) => (text.length > MAX_LABEL ? `${text.slice(0, MAX_LABEL - 1)}…` : text)
const transparent = (c: RGBA): RGBA => [c[0], c[1], c[2], 0]

/**
 * 전체 기간 노드·관계를 한 번 올려 두고, 프레임마다 보이기/숨기기와 크기·색만 바꾼다 (DECISIONS D14).
 * 바뀔 때는 사이 값을 그려 부드럽게 옮겨 가고, 새로 나타난 노드에는 물결을 한 번 그린다 (D20).
 * 선택·강조·관심 대상 표시는 그래프 위 투명 캔버스에 잉크색 링으로 그린다.
 */
export default function GraphView(props: GraphViewProps) {
  const container = useRef<HTMLDivElement>(null)
  const overlay = useRef<HTMLCanvasElement>(null)
  const card = useRef<HTMLDivElement>(null)
  const sigma = useRef<Sigma<NodeAttrs, EdgeAttrs> | null>(null)
  const graph = useRef<Graph<NodeAttrs, EdgeAttrs> | null>(null)
  const palette = useRef<Palette | null>(null)

  const nodeVis = useRef(new Map<string, Vis>())
  const edgeVis = useRef(new Map<string, Vis>())
  const nodeTw = useRef(new Map<string, Tween>())
  const edgeTw = useRef(new Map<string, Tween>())
  const pulses = useRef(new Map<string, number>())
  const rings = useRef<{ root: string | null; selected: string | null; breathing: string[] }>({ root: null, selected: null, breathing: [] })
  const hoverRef = useRef<string | null>(null)
  const raf = useRef<number | null>(null)
  const firstSync = useRef(true)
  const draw = useRef<(now: number) => void>(() => {})
  const kick = useRef<() => void>(() => {})

  const [hover, setHover] = useState<string | null>(null)
  const onSelect = useRef(props.onSelect)
  useEffect(() => {
    onSelect.current = props.onSelect
  }, [props.onSelect])

  const { frames, positions, theme } = props

  // 데이터 범위나 테마가 바뀌면 그래프를 새로 만든다
  useEffect(() => {
    const host = container.current
    const canvas = overlay.current
    if (!host || !canvas) return
    const p = readPalette()
    palette.current = p
    const g = new Graph<NodeAttrs, EdgeAttrs>({ type: 'directed', multi: true })
    for (const [id, meta] of Object.entries(frames.nodes)) {
      const pos = positions[id] ?? { x: 0, y: 0 }
      g.addNode(id, { ...pos, size: 0, color: p.dormant, label: shortLabel(meta.label), shape: 'circle', hidden: true, forceLabel: false, zIndex: 0 })
    }
    for (const [id, meta] of Object.entries(frames.edges)) {
      if (g.hasNode(meta.source) && g.hasNode(meta.target)) {
        g.addDirectedEdgeWithKey(id, meta.source, meta.target, { size: 1, color: p.edgeCandidate, dash: 100000, gap: 1, hidden: true, zIndex: 0 })
      }
    }
    graph.current = g
    nodeVis.current.clear()
    edgeVis.current.clear()
    nodeTw.current.clear()
    edgeTw.current.clear()
    pulses.current.clear()
    firstSync.current = true

    const s = new Sigma<NodeAttrs, EdgeAttrs>(g, host, {
      primitives: {
        nodes: {
          shapes: [sdfCircle(), sdfDiamond()],
          layers: [layerFill()],
          label: { font: { family: LABEL_FONT, weight: '500' }, margin: 6 },
        },
        edges: {
          paths: [pathLine()],
          // 선마다 다른 점선 간격을 쓰려면 변수로 선언해야 셰이더까지 값이 간다
          variables: { dash: { type: 'number', default: 100000 }, gap: { type: 'number', default: 1 } },
          // 실선은 아주 긴 대시 하나로, 발견 후보는 4px 대시 + 3px 간격으로 그린다 (간격 0은 그려지지 않는다)
          layers: [
            layerDashed({
              dashSize: { attribute: 'dash', default: 100000, mode: 'pixels' },
              gapSize: { attribute: 'gap', default: 1, mode: 'pixels' },
            }),
          ],
        },
      },
      styles: {
        nodes: {
          ...DEFAULT_STYLES.nodes,
          size: { attribute: 'size', defaultValue: 0 },
          shape: { attribute: 'shape', defaultValue: 'circle' },
          visibility: (a: NodeAttrs) => (a.hidden ? 'hidden' : 'visible'),
          labelVisibility: (a: NodeAttrs, state: { isHovered: boolean }) =>
            a.hidden ? 'hidden' : a.forceLabel || state.isHovered ? 'visible' : 'auto',
          labelColor: p.label,
          labelSize: 12,
          backdropColor: p.surface,
          backdropShadowColor: 'rgba(0, 0, 0, 0.18)',
          zIndex: { attribute: 'zIndex', defaultValue: 0 },
          cursor: 'pointer',
        },
        edges: {
          ...DEFAULT_STYLES.edges,
          visibility: (a: EdgeAttrs) => (a.hidden ? 'hidden' : 'visible'),
          zIndex: { attribute: 'zIndex', defaultValue: 0 },
          cursor: 'pointer',
        },
      },
      settings: {
        renderEdgeLabels: false,
        enableEdgeEvents: true,
        labelRenderedSizeThreshold: 4,
        labelDensity: 0.7,
        stagePadding: 72,
        autoRescale: true,
        // 크기는 화면 픽셀 기준 (기본값 positions는 좌표 단위라 레이아웃 크기에 따라 달라진다)
        itemSizesReference: 'screen',
        zoomDuration: 280,
        inertiaDuration: 420,
      },
    } as never)
    s.on('clickNode', ({ node }) => onSelect.current({ kind: 'node', id: node }))
    s.on('clickEdge', ({ edge }) => onSelect.current({ kind: 'edge', id: edge }))
    s.on('clickStage', () => onSelect.current(null))
    s.on('enterNode', ({ node }) => {
      hoverRef.current = node
      setHover(node)
    })
    s.on('leaveNode', () => {
      hoverRef.current = null
      setHover(null)
    })
    s.on('afterRender', () => draw.current(performance.now()))
    sigma.current = s

    // 오버레이 캔버스: 링·물결·호버 카드 위치
    const ctx = canvas.getContext('2d')
    const fit = () => {
      const dpr = window.devicePixelRatio || 1
      canvas.width = Math.round(host.clientWidth * dpr)
      canvas.height = Math.round(host.clientHeight * dpr)
      ctx?.setTransform(dpr, 0, 0, dpr, 0, 0)
      draw.current(performance.now())
    }
    const ro = typeof ResizeObserver === 'function' ? new ResizeObserver(fit) : null
    ro?.observe(host)
    fit()

    const ringAt = (id: string) => {
      if (!g.hasNode(id) || g.getNodeAttribute(id, 'hidden')) return null
      const d = s.getNodeDisplayData(id)
      if (!d) return null
      const pt = s.framedGraphToViewport(d)
      return { x: pt.x, y: pt.y, r: s.scaleSize(d.size) }
    }
    draw.current = (now: number) => {
      if (!ctx) return
      ctx.clearRect(0, 0, host.clientWidth, host.clientHeight)
      const focus = parseColor(p.focus)
      const stroke = (x: number, y: number, r: number, width: number, color: RGBA) => {
        ctx.beginPath()
        ctx.arc(x, y, Math.max(r, 0), 0, Math.PI * 2)
        ctx.lineWidth = width
        ctx.strokeStyle = toCss(color)
        ctx.stroke()
      }
      const { root, selected, breathing } = rings.current
      if (root) {
        const a = ringAt(root)
        if (a) stroke(a.x, a.y, a.r + 4, 1, [focus[0], focus[1], focus[2], 0.22])
      }
      for (const [id, start] of pulses.current) {
        const a = ringAt(id)
        const t = Math.min(1, (now - start) / PULSE_MS)
        if (!a) continue
        const c = nodeVis.current.get(id)?.color ?? focus
        const e = easeOutCubic(t)
        stroke(a.x, a.y, a.r + 3 + 26 * e, 0.5 + 1.5 * (1 - t), [c[0], c[1], c[2], 0.55 * (1 - t)])
        if (t < 0.6) stroke(a.x, a.y, a.r + 2 + 12 * easeOutCubic(t / 0.6), 1, [c[0], c[1], c[2], 0.3 * (1 - t / 0.6)])
      }
      const k = 0.5 - 0.5 * Math.cos(((now % BREATH_MS) / BREATH_MS) * Math.PI * 2)
      for (const id of breathing) {
        const a = ringAt(id)
        if (!a) continue
        const halo = ctx.createRadialGradient(a.x, a.y, a.r, a.x, a.y, a.r + 18)
        halo.addColorStop(0, toCss([focus[0], focus[1], focus[2], 0.1 + 0.08 * k]))
        halo.addColorStop(1, toCss([focus[0], focus[1], focus[2], 0]))
        ctx.fillStyle = halo
        ctx.beginPath()
        ctx.arc(a.x, a.y, a.r + 18, 0, Math.PI * 2)
        ctx.fill()
        stroke(a.x, a.y, a.r + 4 + 3 * k, 1.5, [focus[0], focus[1], focus[2], 0.45 + 0.4 * k])
      }
      if (selected) {
        const a = ringAt(selected)
        if (a) {
          stroke(a.x, a.y, a.r + 4, 1.75, [focus[0], focus[1], focus[2], 0.95])
          stroke(a.x, a.y, a.r + 9, 1, [focus[0], focus[1], focus[2], 0.14])
        }
      }
      // 호버 카드는 노드 옆에 붙인다 (React 렌더 없이 위치만 옮긴다)
      const el = card.current
      const hid = hoverRef.current
      if (el && hid) {
        const a = ringAt(hid)
        if (a) {
          const w = el.offsetWidth || 200
          const right = a.x + a.r + 12 + w < host.clientWidth
          const x = right ? a.x + a.r + 12 : a.x - a.r - 12 - w
          const y = Math.min(Math.max(8, a.y - 18), host.clientHeight - (el.offsetHeight || 80) - 8)
          el.style.transform = `translate(${Math.round(x)}px, ${Math.round(y)}px)`
        }
      }
    }

    const loop = (now: number) => {
      const step = (tweens: Map<string, Tween>, vis: Map<string, Vis>, apply: (id: string, v: Vis, done: boolean, tw: Tween) => void) => {
        for (const [id, tw] of tweens) {
          if (now < tw.start) continue // 아직 시작 전 (처음 열 때 차례로 나타나기)
          const t = tw.dur <= 0 ? 1 : Math.min(1, (now - tw.start) / tw.dur)
          const e = tw.ease(t)
          const v: Vis = { size: Math.max(0, lerp(tw.from.size, tw.to.size, e)), color: mixColor(tw.from.color, tw.to.color, Math.min(1, Math.max(0, e))) }
          vis.set(id, v)
          apply(id, v, t >= 1, tw)
          if (t >= 1) tweens.delete(id)
        }
      }
      step(nodeTw.current, nodeVis.current, (id, v, done, tw) => {
        if (!g.hasNode(id)) return
        g.mergeNodeAttributes(id, done && tw.hideAtEnd ? { size: v.size, color: toCss(v.color), hidden: true } : { size: v.size, color: toCss(v.color) })
      })
      step(edgeTw.current, edgeVis.current, (id, v, done, tw) => {
        if (!g.hasEdge(id)) return
        g.mergeEdgeAttributes(id, done && tw.hideAtEnd ? { size: v.size, color: toCss(v.color), hidden: true } : { size: v.size, color: toCss(v.color) })
      })
      for (const [id, start] of pulses.current) if (now - start > PULSE_MS) pulses.current.delete(id)
      draw.current(now)
      const busy = nodeTw.current.size > 0 || edgeTw.current.size > 0 || pulses.current.size > 0 || rings.current.breathing.length > 0
      raf.current = busy ? requestAnimationFrame(loop) : null
    }
    kick.current = () => {
      if (raf.current === null) raf.current = requestAnimationFrame(loop)
    }

    document.fonts?.ready.then(() => sigma.current === s && s.refresh()).catch(() => {})

    return () => {
      if (raf.current !== null) cancelAnimationFrame(raf.current)
      raf.current = null
      ro?.disconnect()
      s.kill()
      sigma.current = null
      graph.current = null
      draw.current = () => {}
      kick.current = () => {}
    }
  }, [frames, positions, theme])

  // 프레임·필터가 바뀌면 목표 값을 정하고 사이를 움직인다
  const { frameIndex, rootId, selection, highlight, showCoMention, showPending, transitionMs } = props
  useEffect(() => {
    const g = graph.current
    const p = palette.current
    const frame = frames.frames[frameIndex]
    if (!g || !p || !frame) return
    const now = performance.now()
    const reduced = prefersReducedMotion()
    // 처음 열 때는 관심 대상에서 바깥쪽으로 차례로 나타난다 (레이더가 훑듯이)
    const intro = firstSync.current && !reduced
    const instant = reduced
    const dur = instant ? 0 : intro ? 620 : transitionMs
    const origin = (rootId && positions[rootId]) || { x: 0, y: 0 }
    const distance = (id: string) => {
      const q = positions[id]
      return q ? Math.hypot(q.x - origin.x, q.y - origin.y) : 0
    }
    const farthest = Math.max(1e-9, ...Object.keys(frames.nodes).map(distance))
    const delayOf = (id: string) => (intro ? 60 + 700 * (distance(id) / farthest) : 0)
    const lit = new Set(highlight?.nodeIds ?? [])

    const tween = (tweens: Map<string, Tween>, vis: Map<string, Vis>, id: string, from: Vis, to: Vis, ease: Tween['ease'], hideAtEnd: boolean, apply: (v: Vis, hide: boolean) => void, delay = 0) => {
      if (dur <= 0) {
        tweens.delete(id)
        vis.set(id, to)
        apply(to, hideAtEnd)
        return
      }
      if (delay > 0) apply(from, false) // 시작 전에는 보이지 않는 상태로 둔다
      tweens.set(id, { from, to, start: now + delay, dur, ease, hideAtEnd })
    }

    const shown = new Set<string>()
    g.forEachNode((id, attrs) => {
      const value = frame.nodes[id]
      const pending = value && (value[2] === 'pending_review' || value[1] === 'candidate')
      const visible = !!value && (showPending || !pending || id === rootId)
      const applyNode = (v: Vis, hide: boolean) => g.mergeNodeAttributes(id, { size: v.size, color: toCss(v.color), ...(hide ? { hidden: true } : {}) })
      if (!visible) {
        if (attrs.hidden) return
        const cur = nodeVis.current.get(id) ?? { size: attrs.size, color: parseColor(attrs.color) }
        g.mergeNodeAttributes(id, { forceLabel: false, zIndex: 0 })
        tween(nodeTw.current, nodeVis.current, id, cur, { size: 0, color: transparent(cur.color) }, easeOutCubic, true, applyNode)
        return
      }
      shown.add(id)
      const style = nodeStyle({ type: frames.nodes[id]?.type ?? 'topic', value, isRoot: id === rootId }, p)
      const target: Vis = { size: style.size, color: parseColor(style.color) }
      const entering = attrs.hidden
      const emphasis = id === rootId || lit.has(id) || (selection?.kind === 'node' && selection.id === id)
      g.mergeNodeAttributes(id, { hidden: false, shape: style.shape, forceLabel: emphasis, zIndex: emphasis ? 2 : 0 })
      const from = entering ? { size: 0, color: transparent(target.color) } : (nodeVis.current.get(id) ?? target)
      if (entering && !instant && !intro) pulses.current.set(id, now)
      tween(nodeTw.current, nodeVis.current, id, from, target, entering ? easeOutBack : easeOutCubic, false, applyNode, entering ? delayOf(id) : 0)
    })

    g.forEachEdge((id, attrs, source, target) => {
      const value = frame.edges[id]
      const relation = frames.edges[id]?.relation ?? 'RELATED_TO'
      const visible = !!value && shown.has(source) && shown.has(target) && (showCoMention || relation !== 'CO_MENTIONED_WITH')
      const applyEdge = (v: Vis, hide: boolean) => g.mergeEdgeAttributes(id, { size: v.size, color: toCss(v.color), ...(hide ? { hidden: true } : {}) })
      if (!visible) {
        if (attrs.hidden) return
        const cur = edgeVis.current.get(id) ?? { size: attrs.size, color: parseColor(attrs.color) }
        tween(edgeTw.current, edgeVis.current, id, cur, { size: cur.size, color: transparent(cur.color) }, easeOutCubic, true, applyEdge)
        return
      }
      const isLit = highlight?.edgeId === id || (selection?.kind === 'edge' && selection.id === id)
      const style = edgeStyle({ relation, value, highlighted: isLit }, p)
      const to: Vis = { size: style.size, color: parseColor(style.color) }
      const entering = attrs.hidden
      g.mergeEdgeAttributes(id, { hidden: false, ...(style.gap > 0 ? { dash: 4, gap: style.gap } : { dash: 100000, gap: 1 }), zIndex: isLit ? 2 : value[1] === 'confirmed' ? 1 : 0 })
      const from = entering ? { size: to.size, color: transparent(to.color) } : (edgeVis.current.get(id) ?? to)
      tween(edgeTw.current, edgeVis.current, id, from, to, easeOutCubic, false, applyEdge, entering && intro ? Math.max(delayOf(source), delayOf(target)) + 260 : 0)
    })

    rings.current = {
      root: rootId,
      selected: selection?.kind === 'node' ? selection.id : null,
      breathing: reduced ? [] : [...lit],
    }
    firstSync.current = false
    kick.current()
    draw.current(now)
  }, [frames, frameIndex, rootId, selection, highlight, showCoMention, showPending, positions, theme, transitionMs])

  // 달라진 점을 고르면 그 노드들로 카메라를 부드럽게 옮긴다
  useEffect(() => {
    const s = sigma.current
    if (!s || !highlight || highlight.nodeIds.length === 0) return
    const pts = highlight.nodeIds.map((id) => s.getNodeDisplayData(id)).filter((d): d is NonNullable<typeof d> => !!d)
    if (pts.length === 0) return
    const xs = pts.map((d) => d.x)
    const ys = pts.map((d) => d.y)
    const cam = s.getCamera()
    const span = Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys))
    const ratio = pts.length > 1 ? Math.min(1.1, Math.max(0.4, span * 2.2)) : Math.min(cam.getState().ratio, 0.8)
    cam.animate(
      { x: (Math.max(...xs) + Math.min(...xs)) / 2, y: (Math.max(...ys) + Math.min(...ys)) / 2, ratio },
      { duration: prefersReducedMotion() ? 0 : 700, easing: easeInOutCubic },
    )
  }, [highlight])

  const zoom = (factor: number | null) => {
    const s = sigma.current
    if (!s) return
    const cam = s.getCamera()
    const duration = prefersReducedMotion() ? 0 : 320
    if (factor === null) cam.animate({ x: 0.5, y: 0.5, ratio: 1, angle: 0 }, { duration, easing: easeInOutCubic })
    else cam.animate({ ratio: cam.getState().ratio * factor }, { duration, easing: easeOutCubic })
  }

  const hv = hover ? frames.frames[frameIndex]?.nodes[hover] : undefined
  const hmeta = hover ? frames.nodes[hover] : undefined
  const ctl =
    'grid size-8 place-items-center rounded-md text-nr-text-2 transition-colors duration-[var(--nr-dur-1)] hover:bg-nr-surface-2 hover:text-nr-text'

  return (
    <div className="nr-canvas-bg absolute inset-0 overflow-hidden">
      <div
        ref={container}
        className="absolute inset-0"
        role="img"
        aria-label="관측된 대상과 연결 그래프. 노드나 선을 누르면 오른쪽에 위키와 근거가 열린다."
        data-testid="graph-canvas"
      />
      <canvas ref={overlay} className="pointer-events-none absolute inset-0 size-full" aria-hidden="true" />
      <div
        ref={card}
        className={`pointer-events-none absolute top-0 left-0 w-52 rounded-lg border border-nr-border bg-nr-surface/95 px-3 py-2 shadow-nr backdrop-blur transition-opacity duration-[var(--nr-dur-2)] ${
          hv && hmeta ? 'opacity-100' : 'opacity-0'
        }`}
        aria-hidden="true"
      >
        {hv && hmeta && (
          <>
            <div className="flex items-center gap-1.5 text-[11px] text-nr-muted">
              <span
                className={`inline-block size-2 ${TYPE_GROUP[hmeta.type] === 'narrative' ? 'rotate-45 rounded-[1px]' : 'rounded-full'}`}
                style={{ background: `var(--nr-series-${TYPE_GROUP[hmeta.type] ?? 'concept'})` }}
              />
              {label(NODE_TYPE_LABEL, hmeta.type)} · {label(NODE_STATUS_LABEL, hv[1])}
              {hv[2] === 'pending_review' && <> · {label(MEMBERSHIP_LABEL, hv[2])}</>}
            </div>
            <div className="mt-0.5 text-sm leading-5 font-semibold text-nr-text">{hmeta.label}</div>
            <div className="mt-1.5 grid grid-cols-2 gap-2 text-[11px] text-nr-muted">
              <div>
                <div className="text-sm font-semibold text-nr-text">{hv[0].toFixed(1)}</div>관심도
              </div>
              <div>
                <div className="text-sm font-semibold text-nr-text">{hv[3]}</div>최근 7일 언급
              </div>
            </div>
          </>
        )}
      </div>
      <div className="absolute top-3 right-3 flex flex-col rounded-lg border border-nr-border bg-nr-surface/90 p-0.5 shadow-nr backdrop-blur">
        <button type="button" className={ctl} onClick={() => zoom(1 / 1.6)} aria-label="확대">
          <ZoomInIcon />
        </button>
        <button type="button" className={ctl} onClick={() => zoom(1.6)} aria-label="축소">
          <ZoomOutIcon />
        </button>
        <button type="button" className={ctl} onClick={() => zoom(null)} aria-label="전체 보기">
          <FitIcon />
        </button>
      </div>
    </div>
  )
}
