// 그래프 캔버스 움직임에 쓰는 작은 도구들. CSS 쪽 토큰(--nr-dur-*, --nr-ease-*)과 같은 감각으로 맞춘다.

export type RGBA = [number, number, number, number]

export function prefersReducedMotion(): boolean {
  return typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches
}

export const easeOutCubic = (t: number) => 1 - (1 - t) ** 3
export const easeInOutCubic = (t: number) => (t < 0.5 ? 4 * t ** 3 : 1 - (-2 * t + 2) ** 3 / 2)
/** 끝에서 살짝 넘쳤다가 돌아온다. 새로 나타나는 노드에 쓴다. */
export const easeOutBack = (t: number) => {
  const c1 = 1.25
  const c3 = c1 + 1
  return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2
}

export const lerp = (a: number, b: number, t: number) => a + (b - a) * t

/** '#rrggbb', 'rgb(...)', 'rgba(...)' → [r, g, b, a]. 모르는 형식은 회색. */
export function parseColor(css: string): RGBA {
  const hex = /^#([0-9a-f]{6})$/i.exec(css.trim())
  if (hex) {
    const n = parseInt(hex[1], 16)
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255, 1]
  }
  const fn = /^rgba?\(([^)]+)\)$/i.exec(css.trim())
  if (fn) {
    const parts = fn[1].split(/[\s,/]+/).filter(Boolean).map(Number)
    if (parts.length >= 3 && parts.every((x) => Number.isFinite(x))) {
      return [parts[0], parts[1], parts[2], parts.length > 3 ? parts[3] : 1]
    }
  }
  return [128, 128, 128, 1]
}

export function toCss([r, g, b, a]: RGBA): string {
  return `rgba(${Math.round(r)}, ${Math.round(g)}, ${Math.round(b)}, ${Math.round(a * 1000) / 1000})`
}

export function mixColor(from: RGBA, to: RGBA, t: number): RGBA {
  return [lerp(from[0], to[0], t), lerp(from[1], to[1], t), lerp(from[2], to[2], t), lerp(from[3], to[3], t)]
}

export function withAlpha(color: string, alpha: number): string {
  const [r, g, b] = parseColor(color)
  return toCss([r, g, b, alpha])
}
