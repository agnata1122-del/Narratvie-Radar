import type { PriceBarRow, PriceSeries } from '../api'

/** 재생 시점까지 끝나 있던 봉만 (미래의 시세를 보여주지 않는다, D27) */
export function visibleBars(bars: PriceBarRow[], asOf: string): PriceBarRow[] {
  const t = Date.parse(asOf)
  return bars.filter((b) => Date.parse(b[2]) <= t)
}

/** 구간 시작 직전(또는 첫) 종가 대비 마지막 종가의 변화율(%). 봉이 없으면 null */
export function changeSince(bars: PriceBarRow[], start: string): number | null {
  if (bars.length === 0) return null
  const t = Date.parse(start)
  let base = bars[0]
  for (const b of bars) {
    if (Date.parse(b[2]) <= t) base = b
    else break
  }
  const last = bars[bars.length - 1]
  if (base[1] === 0) return null
  return ((last[1] - base[1]) / base[1]) * 100
}

/** 구간 [start, end]를 가로축으로 쓰는 꺾은선 경로. 종목끼리 같은 시간축에 놓인다 */
export function sparkPath(bars: PriceBarRow[], start: string, end: string, width: number, height: number, pad = 2): string {
  const t0 = Date.parse(start)
  // 구간 앞의 봉은 기준이 되는 마지막 하나만 왼쪽 끝에 둔다 (여러 개가 x=0에 겹치면 세로 줄이 생긴다)
  const firstIn = bars.findIndex((b) => Date.parse(b[2]) >= t0)
  const used = firstIn === -1 ? bars.slice(-1) : bars.slice(Math.max(firstIn - 1, 0))
  if (used.length === 0) return ''
  const t1 = Date.parse(end)
  const span = Math.max(t1 - t0, 1)
  const closes = used.map((b) => b[1])
  const lo = Math.min(...closes)
  const hi = Math.max(...closes)
  const range = hi - lo || 1
  return used
    .map((b, i) => {
      const x = Math.min(Math.max((Date.parse(b[2]) - t0) / span, 0), 1) * width
      const y = pad + (1 - (b[1] - lo) / range) * (height - pad * 2)
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
}

export function formatChange(pct: number | null): string {
  if (pct === null || !Number.isFinite(pct)) return '—'
  const sign = pct > 0 ? '+' : pct < 0 ? '−' : ''
  return `${sign}${Math.abs(pct).toFixed(1)}%`
}

export function changeTone(pct: number | null): 'up' | 'down' | 'flat' {
  if (pct === null || Math.abs(pct) < 0.05) return 'flat'
  return pct > 0 ? 'up' : 'down'
}

export function formatPrice(value: number, currency: string | null, market: PriceSeries['market']): string {
  const cur = currency ?? (market === 'KR' ? 'KRW' : null)
  const digits = cur === 'KRW' ? 0 : 2
  const text = value.toLocaleString('ko-KR', { minimumFractionDigits: digits, maximumFractionDigits: digits })
  if (cur === 'KRW') return `${text}원`
  if (cur === 'USD') return `$${text}`
  return text
}
